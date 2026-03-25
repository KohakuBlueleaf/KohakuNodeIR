//! L1 → L2 compiler: KirGraph (.kirgraph) → KIR Program AST.
//!
//! Port of `src/kohakunode/kirgraph/compiler.py`.
//!
//! Public entry point: [`compile`].

use std::collections::{HashMap, HashSet};

use crate::ast::{
    Assignment, Branch, DataflowBlock, Expression, FuncCall, Identifier, Jump, Literal,
    MetaAnnotation, Namespace, OutputTarget, Parallel, Program, Statement, Switch, Value,
};
use crate::kirgraph::{KGNode, KirGraph};

// ---------------------------------------------------------------------------
// Small helpers — mirrors Python _var / _lit / _meta
// ---------------------------------------------------------------------------

fn var(node_id: &str, port: &str) -> String {
    let prefix = format!("{node_id}_");
    if port.starts_with(&prefix) {
        return port.to_string();
    }
    format!("{node_id}_{port}")
}

fn lit(value: &Value) -> Literal {
    let (v, t) = match value {
        Value::None => (Value::None, "none"),
        Value::Bool(b) => (Value::Bool(*b), "bool"),
        Value::Int(i) => (Value::Int(*i), "int"),
        Value::Float(f) => (Value::Float(*f), "float"),
        Value::Str(s) => (Value::Str(s.clone()), "str"),
        Value::List(l) => (Value::List(l.clone()), "list"),
        Value::Dict(d) => (Value::Dict(d.clone()), "dict"),
    };
    Literal {
        value: v,
        literal_type: t.to_string(),
        line: None,
    }
}

fn lit_zero() -> Literal {
    Literal {
        value: Value::Int(0),
        literal_type: "int".to_string(),
        line: None,
    }
}

fn meta_for(node: &KGNode) -> MetaAnnotation {
    let mut data: HashMap<String, Value> = HashMap::new();
    data.insert("node_id".to_string(), Value::Str(node.id.clone()));
    if let Some(pos) = node.meta.get("pos") {
        data.insert("pos".to_string(), pos.clone());
    }
    for (k, v) in &node.meta {
        if k != "pos" {
            data.insert(k.clone(), v.clone());
        }
    }
    MetaAnnotation { data, line: None }
}

fn ident(name: String) -> Expression {
    Expression::Identifier(Identifier { name, line: None })
}

fn expr_lit(l: Literal) -> Expression {
    Expression::Literal(l)
}

// ---------------------------------------------------------------------------
// Adjacency types
// ---------------------------------------------------------------------------

/// ctrl_out[node_id] = [(from_port, to_node, to_port), ...]
type CtrlOut = HashMap<String, Vec<(String, String, String)>>;
/// ctrl_in[node_id] = [(from_node, from_port, to_port), ...]
type CtrlIn = HashMap<String, Vec<(String, String, String)>>;
/// data_in[node_id][to_port] = (from_node, from_port)
type DataIn = HashMap<String, HashMap<String, (String, String)>>;

// ---------------------------------------------------------------------------
// KirGraphCompiler
// ---------------------------------------------------------------------------

struct KirGraphCompiler {
    nodes: HashMap<String, KGNode>,
    ctrl_out: CtrlOut,
    ctrl_in: CtrlIn,
    data_in: DataIn,
    ctrl_connected: HashSet<String>,
    /// node_id → set of connected ctrl_in port names
    connected_ctrl_in_ports: HashMap<String, HashSet<String>>,
    visited: HashSet<String>,
    /// (node_id, in_port) → feedback var name (own output var)
    feedback_vars: HashMap<(String, String), String>,
    /// nodes that are in some loop body
    loop_body_nodes: HashSet<String>,
    /// non-ctrl nodes that depend on ctrl outputs (emitted after their sources)
    dependent_nodes: HashMap<String, KGNode>,
}

impl KirGraphCompiler {
    fn new(graph: &KirGraph) -> Self {
        let nodes: HashMap<String, KGNode> = graph
            .nodes
            .iter()
            .map(|n| (n.id.clone(), n.clone()))
            .collect();

        let mut ctrl_out: CtrlOut = HashMap::new();
        let mut ctrl_in: CtrlIn = HashMap::new();
        let mut data_in: DataIn = HashMap::new();
        let mut ctrl_connected: HashSet<String> = HashSet::new();
        let mut connected_ctrl_in_ports: HashMap<String, HashSet<String>> = HashMap::new();

        for edge in &graph.edges {
            if edge.r#type == "control" {
                ctrl_out.entry(edge.from_node.clone()).or_default().push((
                    edge.from_port.clone(),
                    edge.to_node.clone(),
                    edge.to_port.clone(),
                ));
                ctrl_in.entry(edge.to_node.clone()).or_default().push((
                    edge.from_node.clone(),
                    edge.from_port.clone(),
                    edge.to_port.clone(),
                ));
                ctrl_connected.insert(edge.from_node.clone());
                ctrl_connected.insert(edge.to_node.clone());
                connected_ctrl_in_ports
                    .entry(edge.to_node.clone())
                    .or_default()
                    .insert(edge.to_port.clone());
            } else {
                data_in.entry(edge.to_node.clone()).or_default().insert(
                    edge.to_port.clone(),
                    (edge.from_node.clone(), edge.from_port.clone()),
                );
            }
        }

        KirGraphCompiler {
            nodes,
            ctrl_out,
            ctrl_in,
            data_in,
            ctrl_connected,
            connected_ctrl_in_ports,
            visited: HashSet::new(),
            feedback_vars: HashMap::new(),
            loop_body_nodes: HashSet::new(),
            dependent_nodes: HashMap::new(),
        }
    }

    // ── Loop body detection ────────────────────────────────────────────────

    fn build_loop_info(&mut self) {
        let merge_ids: Vec<String> = self
            .nodes
            .values()
            .filter(|n| n.r#type == "merge")
            .map(|n| n.id.clone())
            .collect();

        for merge_id in &merge_ids {
            let mut body = self.reachable(merge_id);
            body.remove(merge_id);
            self.loop_body_nodes.extend(body);
        }

        if self.loop_body_nodes.is_empty() {
            return;
        }

        let loop_body_snapshot: Vec<String> = self.loop_body_nodes.iter().cloned().collect();
        let merge_ids_set: HashSet<String> = merge_ids.into_iter().collect();

        for nid in &loop_body_snapshot {
            let node = match self.nodes.get(nid) {
                Some(n) if !n.data_outputs.is_empty() => n.clone(),
                _ => continue,
            };
            let conn: HashMap<String, (String, String)> =
                self.data_in.get(nid).cloned().unwrap_or_default();
            for (in_port, (src_node, _src_port)) in &conn {
                if !self.loop_body_nodes.contains(src_node) && !merge_ids_set.contains(src_node) {
                    // Input crosses loop boundary from initial value
                    let in_idx = node.data_inputs.iter().position(|p| &p.port == in_port);
                    if let Some(idx) = in_idx {
                        if idx < node.data_outputs.len() {
                            let out_port = node.data_outputs[idx].port.clone();
                            let fb_var = var(nid, &out_port);
                            self.feedback_vars
                                .insert((nid.clone(), in_port.clone()), fb_var);
                        }
                    }
                }
            }
        }
    }

    // ── Data input resolution ──────────────────────────────────────────────

    fn input_expr(&self, node: &KGNode, port: &str) -> Expression {
        // Check feedback variable (loop self-reference)
        if let Some(fb) = self.feedback_vars.get(&(node.id.clone(), port.to_string())) {
            return ident(fb.clone());
        }
        if let Some(conn) = self.data_in.get(&node.id) {
            if let Some((src_node, src_port)) = conn.get(port) {
                return ident(var(src_node, src_port));
            }
        }
        // Fall back to declared default
        for p in &node.data_inputs {
            if p.port == port {
                if let Some(ref default) = p.default {
                    return expr_lit(lit(default));
                }
            }
        }
        expr_lit(lit_zero())
    }

    // ── Emit single ctrl-connected node ───────────────────────────────────

    fn emit_node(&mut self, node: &KGNode) -> Vec<Statement> {
        let m = meta_for(node);
        let mut stmts: Vec<Statement> = Vec::new();

        match node.r#type.as_str() {
            "value" => {
                let val = node
                    .properties
                    .get("value")
                    .cloned()
                    .unwrap_or(Value::Int(0));
                let out = node
                    .data_outputs
                    .first()
                    .map(|p| p.port.clone())
                    .unwrap_or_else(|| "value".to_string());
                stmts.push(Statement::Assignment(Assignment {
                    target: var(&node.id, &out),
                    value: expr_lit(lit(&val)),
                    type_annotation: None,
                    metadata: Some(vec![m]),
                    line: None,
                }));
            }
            "merge" => {
                // merge nodes are handled in walk(), not here
            }
            "branch" => {
                stmts.extend(self.emit_branch(node, m));
            }
            "switch" => {
                stmts.extend(self.emit_switch(node, m));
            }
            "parallel" => {
                stmts.extend(self.emit_parallel(node, m));
            }
            _ => {
                let inputs: Vec<Expression> = node
                    .data_inputs
                    .iter()
                    .map(|p| self.input_expr(node, &p.port))
                    .collect();
                let outputs: Vec<OutputTarget> = node
                    .data_outputs
                    .iter()
                    .map(|p| OutputTarget::Name(var(&node.id, &p.port)))
                    .collect();
                stmts.push(Statement::FuncCall(FuncCall {
                    inputs,
                    func_name: node.r#type.clone(),
                    outputs,
                    metadata: Some(vec![m]),
                    line: None,
                }));
            }
        }

        // After emitting this ctrl node, also emit any dependent non-ctrl nodes
        // whose data inputs are now all satisfied.
        let node_id = node.id.clone();
        stmts.extend(self.emit_ready_dependents(&node_id));
        stmts
    }

    fn emit_ready_dependents(&mut self, _just_emitted: &str) -> Vec<Statement> {
        let mut df_stmts: Vec<Statement> = Vec::new();
        let mut emitted_ids: HashSet<String> = HashSet::new();

        let mut changed = true;
        while changed {
            changed = false;
            let pending: Vec<String> = self.dependent_nodes.keys().cloned().collect();
            for nid in pending {
                if emitted_ids.contains(&nid) {
                    continue;
                }
                if self.all_data_sources_emitted(&nid, &emitted_ids) {
                    let node = self.dependent_nodes.remove(&nid).unwrap();
                    emitted_ids.insert(nid);
                    df_stmts.extend(self.emit_node_raw(&node));
                    changed = true;
                }
            }
        }

        if df_stmts.is_empty() {
            return Vec::new();
        }
        vec![Statement::DataflowBlock(DataflowBlock {
            body: df_stmts,
            line: None,
        })]
    }

    fn all_data_sources_emitted(&self, node_id: &str, extra: &HashSet<String>) -> bool {
        if let Some(conn) = self.data_in.get(node_id) {
            for (src_node, _) in conn.values() {
                if !self.visited.contains(src_node) && !extra.contains(src_node) {
                    return false;
                }
            }
        }
        true
    }

    /// Emit a non-ctrl node without triggering dependent cascades.
    fn emit_node_raw(&self, node: &KGNode) -> Vec<Statement> {
        let m = meta_for(node);
        if node.r#type == "value" {
            let val = node
                .properties
                .get("value")
                .cloned()
                .unwrap_or(Value::Int(0));
            let out = node
                .data_outputs
                .first()
                .map(|p| p.port.clone())
                .unwrap_or_else(|| "value".to_string());
            return vec![Statement::Assignment(Assignment {
                target: var(&node.id, &out),
                value: expr_lit(lit(&val)),
                type_annotation: None,
                metadata: Some(vec![m]),
                line: None,
            })];
        }
        let inputs: Vec<Expression> = node
            .data_inputs
            .iter()
            .map(|p| self.input_expr(node, &p.port))
            .collect();
        let outputs: Vec<OutputTarget> = node
            .data_outputs
            .iter()
            .map(|p| OutputTarget::Name(var(&node.id, &p.port)))
            .collect();
        vec![Statement::FuncCall(FuncCall {
            inputs,
            func_name: node.r#type.clone(),
            outputs,
            metadata: Some(vec![m]),
            line: None,
        })]
    }

    // ── Branch / Switch / Parallel emission ───────────────────────────────

    fn emit_branch(&mut self, node: &KGNode, m: MetaAnnotation) -> Vec<Statement> {
        let cond = self.input_expr(node, "condition");
        let tp = node
            .ctrl_outputs
            .first()
            .cloned()
            .unwrap_or_else(|| "true".to_string());
        let fp = node
            .ctrl_outputs
            .get(1)
            .cloned()
            .unwrap_or_else(|| "false".to_string());
        let tl = format!("{}_{}", node.id, tp);
        let fl = format!("{}_{}", node.id, fp);
        let mut stmts: Vec<Statement> = vec![Statement::Branch(Branch {
            condition: cond,
            true_label: tl.clone(),
            false_label: fl.clone(),
            metadata: Some(vec![m]),
            line: None,
        })];
        let node_id = node.id.clone();
        for (port, label) in [(&tp.clone(), &tl.clone()), (&fp.clone(), &fl.clone())] {
            let body = self.chain_from_port(&node_id, port);
            stmts.push(Statement::Namespace(Namespace {
                name: label.clone(),
                body,
                line: None,
            }));
        }
        stmts
    }

    fn emit_switch(&mut self, node: &KGNode, m: MetaAnnotation) -> Vec<Statement> {
        let val = self.input_expr(node, "value");
        let cp: HashMap<String, Value> = node
            .properties
            .get("cases")
            .and_then(|v| {
                if let Value::Dict(d) = v {
                    Some(d.clone())
                } else {
                    None
                }
            })
            .unwrap_or_default();

        let mut cases: Vec<(Expression, String)> = Vec::new();
        let mut default_label: Option<String> = None;
        let mut labels: Vec<(String, String)> = Vec::new();

        for port in node.ctrl_outputs.clone() {
            let label = format!("{}_{}", node.id, port);
            let is_default = cp
                .get(&port)
                .map_or(false, |v| matches!(v, Value::Str(s) if s == "_default_"))
                || port == "default";
            if is_default {
                default_label = Some(label.clone());
            } else if let Some(case_val) = cp.get(&port) {
                cases.push((expr_lit(lit(case_val)), label.clone()));
            } else {
                cases.push((expr_lit(lit(&Value::Str(port.clone()))), label.clone()));
            }
            labels.push((port, label));
        }

        let mut stmts: Vec<Statement> = vec![Statement::Switch(Switch {
            value: val,
            cases,
            default_label,
            metadata: Some(vec![m]),
            line: None,
        })];
        let node_id = node.id.clone();
        for (port, label) in labels {
            let body = self.chain_from_port(&node_id, &port);
            stmts.push(Statement::Namespace(Namespace {
                name: label,
                body,
                line: None,
            }));
        }
        stmts
    }

    fn emit_parallel(&mut self, node: &KGNode, m: MetaAnnotation) -> Vec<Statement> {
        let labels: Vec<String> = node
            .ctrl_outputs
            .iter()
            .map(|p| format!("{}_{}", node.id, p))
            .collect();
        let mut stmts: Vec<Statement> = vec![Statement::Parallel(Parallel {
            labels: labels.clone(),
            metadata: Some(vec![m]),
            line: None,
        })];
        let ports: Vec<String> = node.ctrl_outputs.clone();
        let node_id = node.id.clone();
        for (port, label) in ports.iter().zip(labels.iter()) {
            let body = self.chain_from_port(&node_id, port);
            stmts.push(Statement::Namespace(Namespace {
                name: label.clone(),
                body,
                line: None,
            }));
        }
        stmts
    }

    // ── Control chain walking ──────────────────────────────────────────────

    fn emit_ctrl(&mut self, ctrl_nodes: &[KGNode]) -> Vec<Statement> {
        // Entry = ctrl node with no incoming ctrl edges, OR a merge with some
        // unconnected ctrl_in ports (loop entry point).
        let mut entry_ids: Vec<String> = Vec::new();
        for n in ctrl_nodes {
            let ins = self.ctrl_in.get(&n.id).map(|v| v.len()).unwrap_or(0);
            if ins == 0 {
                entry_ids.push(n.id.clone());
            } else if n.r#type == "merge" {
                let connected = self
                    .connected_ctrl_in_ports
                    .get(&n.id)
                    .map(|s| s.len())
                    .unwrap_or(0);
                if connected < n.ctrl_inputs.len() {
                    entry_ids.push(n.id.clone());
                }
            }
        }

        if entry_ids.is_empty() {
            // Fall back: pick topmost node by visual position (y then x)
            let mut sorted = ctrl_nodes.to_vec();
            sorted.sort_by(|a, b| {
                let pa = get_pos(&a.meta);
                let pb = get_pos(&b.meta);
                pa.1.partial_cmp(&pb.1)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then(pa.0.partial_cmp(&pb.0).unwrap_or(std::cmp::Ordering::Equal))
            });
            if let Some(first) = sorted.first() {
                entry_ids.push(first.id.clone());
            }
        }

        let mut stmts: Vec<Statement> = Vec::new();
        for eid in entry_ids {
            stmts.extend(self.walk(&eid));
        }
        stmts
    }

    fn walk(&mut self, start: &str) -> Vec<Statement> {
        let mut stmts: Vec<Statement> = Vec::new();
        let mut cur: Option<String> = Some(start.to_string());

        while let Some(cur_id) = cur.clone() {
            if self.visited.contains(&cur_id) {
                // Back edge → jump to existing namespace
                stmts.push(Statement::Jump(Jump {
                    target: format!("ns_{cur_id}"),
                    metadata: None,
                    line: None,
                }));
                break;
            }

            let node = self.nodes[&cur_id].clone();

            if node.r#type == "merge" {
                let ns_label = format!("ns_{cur_id}");
                let merge_meta = meta_for(&node);
                self.visited.insert(cur_id.clone());
                let next_id = self.next_node(&node);

                // Emit initialization assignments for feedback variables.
                // These bridge the initial value → loop variable before the
                // first iteration.
                let fb_entries: Vec<((String, String), String)> = self
                    .feedback_vars
                    .iter()
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect();
                for ((nid, in_port), fb_var) in fb_entries {
                    if let Some(conn) = self.data_in.get(&nid) {
                        if let Some((src_node, src_port)) = conn.get(&in_port) {
                            let init_var = var(src_node, src_port);
                            if init_var != fb_var {
                                stmts.push(Statement::Assignment(Assignment {
                                    target: fb_var,
                                    value: ident(init_var),
                                    type_annotation: None,
                                    metadata: None,
                                    line: None,
                                }));
                            }
                        }
                    }
                }

                let inner = match next_id {
                    Some(ref nid) => self.walk(nid),
                    None => Vec::new(),
                };
                stmts.push(Statement::Jump(Jump {
                    target: ns_label.clone(),
                    metadata: Some(vec![merge_meta]),
                    line: None,
                }));
                stmts.push(Statement::Namespace(Namespace {
                    name: ns_label,
                    body: inner,
                    line: None,
                }));
                break;
            }

            self.visited.insert(cur_id.clone());
            let emitted = self.emit_node(&node);
            stmts.extend(emitted);

            if matches!(node.r#type.as_str(), "branch" | "switch" | "parallel") {
                let merge_id = self.find_merge(&node);
                cur = match merge_id {
                    Some(ref mid) if !self.visited.contains(mid) => Some(mid.clone()),
                    _ => None,
                };
            } else {
                cur = self.next_node(&node);
            }
        }

        stmts
    }

    fn chain_from_port(&mut self, node_id: &str, port: &str) -> Vec<Statement> {
        let target = self.ctrl_out.get(node_id).and_then(|outs| {
            outs.iter()
                .find(|(fp, _, _)| fp == port)
                .map(|(_, to, _)| to.clone())
        });
        match target {
            Some(to_id) => self.walk(&to_id),
            None => Vec::new(),
        }
    }

    fn next_node(&self, node: &KGNode) -> Option<String> {
        let outs = self.ctrl_out.get(&node.id)?;
        if outs.len() == 1 {
            Some(outs[0].1.clone())
        } else {
            None
        }
    }

    fn find_merge(&self, node: &KGNode) -> Option<String> {
        let outs = self.ctrl_out.get(&node.id)?;
        if outs.is_empty() {
            return None;
        }
        let mut sets: Vec<HashSet<String>> =
            outs.iter().map(|(_, to, _)| self.reachable(to)).collect();
        let mut common = sets.remove(0);
        for s in sets {
            common.retain(|x| s.contains(x));
        }
        // Prefer a node explicitly typed "merge"
        for nid in &common {
            if self.nodes.get(nid).map_or(false, |n| n.r#type == "merge") {
                return Some(nid.clone());
            }
        }
        // Fallback: any node with >= 2 incoming ctrl edges
        for nid in &common {
            if self.ctrl_in.get(nid).map_or(0, |v| v.len()) >= 2 {
                return Some(nid.clone());
            }
        }
        None
    }

    fn reachable(&self, start: &str) -> HashSet<String> {
        let mut vis: HashSet<String> = HashSet::new();
        let mut stack: Vec<String> = vec![start.to_string()];
        while let Some(nid) = stack.pop() {
            if vis.contains(&nid) {
                continue;
            }
            vis.insert(nid.clone());
            if let Some(outs) = self.ctrl_out.get(&nid) {
                for (_, to, _) in outs {
                    stack.push(to.clone());
                }
            }
        }
        vis
    }

    fn depends_on_ctrl(&self, node_id: &str) -> bool {
        let mut visited: HashSet<String> = HashSet::new();
        let mut stack: Vec<String> = vec![node_id.to_string()];
        while let Some(nid) = stack.pop() {
            if visited.contains(&nid) {
                continue;
            }
            visited.insert(nid.clone());
            if let Some(conn) = self.data_in.get(&nid) {
                for (src_node, _) in conn.values() {
                    if self.ctrl_connected.contains(src_node) {
                        return true;
                    }
                    stack.push(src_node.clone());
                }
            }
        }
        false
    }

    // ── Top-level compile ─────────────────────────────────────────────────

    fn compile(&mut self, graph: &KirGraph) -> Program {
        self.build_loop_info();

        let ctrl_nodes: Vec<KGNode> = graph
            .nodes
            .iter()
            .filter(|n| self.ctrl_connected.contains(&n.id))
            .cloned()
            .collect();
        let unconnected: Vec<KGNode> = graph
            .nodes
            .iter()
            .filter(|n| !self.ctrl_connected.contains(&n.id))
            .cloned()
            .collect();

        let mut independent: Vec<KGNode> = Vec::new();
        for n in unconnected {
            if self.depends_on_ctrl(&n.id) {
                self.dependent_nodes.insert(n.id.clone(), n);
            } else {
                independent.push(n);
            }
        }

        let mut body: Vec<Statement> = Vec::new();

        if !independent.is_empty() {
            let df_body: Vec<Statement> = independent
                .iter()
                .flat_map(|n| self.emit_node_raw(n))
                .collect();
            body.push(Statement::DataflowBlock(DataflowBlock {
                body: df_body,
                line: None,
            }));
            for n in &independent {
                self.visited.insert(n.id.clone());
            }
        }

        if !ctrl_nodes.is_empty() {
            body.extend(self.emit_ctrl(&ctrl_nodes.clone()));
        }

        Program {
            body,
            mode: None,
            typehints: None,
            line: None,
        }
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn get_pos(meta: &HashMap<String, Value>) -> (f64, f64) {
    if let Some(Value::List(l)) = meta.get("pos") {
        let x = match l.first() {
            Some(Value::Float(f)) => *f,
            Some(Value::Int(i)) => *i as f64,
            _ => 0.0,
        };
        let y = match l.get(1) {
            Some(Value::Float(f)) => *f,
            Some(Value::Int(i)) => *i as f64,
            _ => 0.0,
        };
        return (x, y);
    }
    (0.0, 0.0)
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Compile a [`KirGraph`] (L1) into a KIR [`Program`] AST (L2).
pub fn compile(graph: &KirGraph) -> Program {
    let mut compiler = KirGraphCompiler::new(graph);
    compiler.compile(graph)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kirgraph::{KGEdge, KGNode, KGPort, KirGraph};
    use crate::serializer;
    use std::collections::HashMap;

    // ── helpers ──────────────────────────────────────────────────────────────

    fn value_node(id: &str, val: i64) -> KGNode {
        KGNode {
            id: id.to_string(),
            r#type: "value".to_string(),
            name: "Value".to_string(),
            data_inputs: vec![],
            data_outputs: vec![KGPort::with_type("value", "int")],
            ctrl_inputs: vec![],
            ctrl_outputs: vec![],
            properties: {
                let mut m = HashMap::new();
                m.insert("value".to_string(), Value::Int(val));
                m
            },
            meta: HashMap::new(),
        }
    }

    fn func_node(id: &str, type_: &str, inputs: Vec<&str>, outputs: Vec<&str>) -> KGNode {
        KGNode {
            id: id.to_string(),
            r#type: type_.to_string(),
            name: type_.to_string(),
            data_inputs: inputs
                .iter()
                .map(|p| KGPort::with_type(*p, "any"))
                .collect(),
            data_outputs: outputs
                .iter()
                .map(|p| KGPort::with_type(*p, "any"))
                .collect(),
            ctrl_inputs: vec![],
            ctrl_outputs: vec![],
            properties: HashMap::new(),
            meta: HashMap::new(),
        }
    }

    // ── tests ─────────────────────────────────────────────────────────────────

    /// value → add → print: fully independent (no ctrl edges), emitted in @dataflow.
    #[test]
    fn test_simple_dataflow_graph() {
        let mut g = KirGraph::default();
        g.nodes.push(value_node("v1", 10));
        g.nodes.push(value_node("v2", 20));
        g.nodes
            .push(func_node("add1", "add", vec!["a", "b"], vec!["result"]));
        g.nodes
            .push(func_node("print1", "print", vec!["x"], vec![]));
        g.edges.push(KGEdge::data("v1", "value", "add1", "a"));
        g.edges.push(KGEdge::data("v2", "value", "add1", "b"));
        g.edges.push(KGEdge::data("add1", "result", "print1", "x"));

        let prog = compile(&g);
        let kir = serializer::write(&prog);

        assert!(
            kir.contains("@dataflow:"),
            "expected @dataflow block, got:\n{kir}"
        );
        assert!(kir.contains("v1_value = 10"), "got:\n{kir}");
        assert!(kir.contains("v2_value = 20"), "got:\n{kir}");
        assert!(kir.contains("add(add1_result)"), "got:\n{kir}");
        assert!(kir.contains("print1"), "got:\n{kir}");
    }

    /// Sequential ctrl chain: entry → work → exit
    #[test]
    fn test_sequential_ctrl_chain() {
        let mut g = KirGraph::default();
        // entry node: ctrl only
        g.nodes.push(KGNode {
            id: "start".to_string(),
            r#type: "entry".to_string(),
            name: "Entry".to_string(),
            data_inputs: vec![],
            data_outputs: vec![],
            ctrl_inputs: vec![],
            ctrl_outputs: vec!["out".to_string()],
            properties: HashMap::new(),
            meta: HashMap::new(),
        });
        // work node: has data input fed by a value node
        let mut work = func_node("work", "do_work", vec!["x"], vec!["y"]);
        work.ctrl_inputs = vec!["in".to_string()];
        work.ctrl_outputs = vec!["out".to_string()];
        g.nodes.push(work);
        // exit node: ctrl only
        g.nodes.push(KGNode {
            id: "end_n".to_string(),
            r#type: "exit".to_string(),
            name: "Exit".to_string(),
            data_inputs: vec![],
            data_outputs: vec![],
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs: vec![],
            properties: HashMap::new(),
            meta: HashMap::new(),
        });
        g.nodes.push(value_node("v1", 5));
        g.edges.push(KGEdge::control("start", "out", "work", "in"));
        g.edges.push(KGEdge::control("work", "out", "end_n", "in"));
        g.edges.push(KGEdge::data("v1", "value", "work", "x"));

        let prog = compile(&g);
        let kir = serializer::write(&prog);

        assert!(
            kir.contains("do_work"),
            "expected do_work call, got:\n{kir}"
        );
    }

    /// Branch pattern: branch → true/false arms
    #[test]
    fn test_branch_pattern() {
        let mut g = KirGraph::default();

        g.nodes.push(value_node("cond_val", 1));
        g.nodes.push(KGNode {
            id: "br".to_string(),
            r#type: "branch".to_string(),
            name: "Branch".to_string(),
            data_inputs: vec![KGPort::with_type("condition", "bool")],
            data_outputs: vec![],
            ctrl_inputs: vec![],
            ctrl_outputs: vec!["true".to_string(), "false".to_string()],
            properties: HashMap::new(),
            meta: HashMap::new(),
        });
        let mut true_fn = func_node("true_fn", "on_true", vec![], vec![]);
        true_fn.ctrl_inputs = vec!["in".to_string()];
        true_fn.ctrl_outputs = vec!["out".to_string()];
        g.nodes.push(true_fn);
        let mut false_fn = func_node("false_fn", "on_false", vec![], vec![]);
        false_fn.ctrl_inputs = vec!["in".to_string()];
        false_fn.ctrl_outputs = vec!["out".to_string()];
        g.nodes.push(false_fn);
        g.nodes.push(KGNode {
            id: "merge1".to_string(),
            r#type: "merge".to_string(),
            name: "Merge".to_string(),
            data_inputs: vec![],
            data_outputs: vec![],
            ctrl_inputs: vec!["a".to_string(), "b".to_string()],
            ctrl_outputs: vec!["out".to_string()],
            properties: HashMap::new(),
            meta: HashMap::new(),
        });

        g.edges
            .push(KGEdge::data("cond_val", "value", "br", "condition"));
        g.edges.push(KGEdge::control("br", "true", "true_fn", "in"));
        g.edges
            .push(KGEdge::control("br", "false", "false_fn", "in"));
        g.edges
            .push(KGEdge::control("true_fn", "out", "merge1", "a"));
        g.edges
            .push(KGEdge::control("false_fn", "out", "merge1", "b"));

        let prog = compile(&g);
        let kir = serializer::write(&prog);

        assert!(
            kir.contains("branch("),
            "expected branch statement, got:\n{kir}"
        );
        assert!(
            kir.contains("br_true"),
            "expected br_true label, got:\n{kir}"
        );
        assert!(
            kir.contains("br_false"),
            "expected br_false label, got:\n{kir}"
        );
    }

    /// Loop pattern: merge → counter → back-edge jump
    #[test]
    fn test_merge_loop_pattern() {
        let mut g = KirGraph::default();

        // Initial value
        g.nodes.push(value_node("init", 0));

        // merge: ctrl_inputs = [entry, back]; only "back" is ctrl-connected
        g.nodes.push(KGNode {
            id: "loop_merge".to_string(),
            r#type: "merge".to_string(),
            name: "Merge".to_string(),
            data_inputs: vec![],
            data_outputs: vec![],
            ctrl_inputs: vec!["entry".to_string(), "back".to_string()],
            ctrl_outputs: vec!["out".to_string()],
            properties: HashMap::new(),
            meta: HashMap::new(),
        });

        // counter: inc(x) → y; inside the loop body
        let mut counter = func_node("counter", "inc", vec!["x"], vec!["y"]);
        counter.ctrl_inputs = vec!["in".to_string()];
        counter.ctrl_outputs = vec!["out".to_string()];
        g.nodes.push(counter);

        // ctrl: merge → counter → back to merge
        g.edges
            .push(KGEdge::control("loop_merge", "out", "counter", "in"));
        g.edges
            .push(KGEdge::control("counter", "out", "loop_merge", "back"));

        // data: initial value → counter's input on first iteration
        g.edges.push(KGEdge::data("init", "value", "counter", "x"));

        let prog = compile(&g);
        let kir = serializer::write(&prog);

        assert!(
            kir.contains("ns_loop_merge:"),
            "expected loop namespace, got:\n{kir}"
        );
        assert!(
            kir.contains("jump(`ns_loop_merge`)"),
            "expected jump, got:\n{kir}"
        );
        // Feedback init: counter_y = init_value
        assert!(
            kir.contains("counter_y = init_value"),
            "expected feedback init assignment, got:\n{kir}"
        );
    }

    /// Parallel pattern
    #[test]
    fn test_parallel_pattern() {
        let mut g = KirGraph::default();

        g.nodes.push(KGNode {
            id: "par".to_string(),
            r#type: "parallel".to_string(),
            name: "Parallel".to_string(),
            data_inputs: vec![],
            data_outputs: vec![],
            ctrl_inputs: vec![],
            ctrl_outputs: vec!["a".to_string(), "b".to_string()],
            properties: HashMap::new(),
            meta: HashMap::new(),
        });
        let mut fa = func_node("fa", "task_a", vec![], vec![]);
        fa.ctrl_inputs = vec!["in".to_string()];
        g.nodes.push(fa);
        let mut fb = func_node("fb", "task_b", vec![], vec![]);
        fb.ctrl_inputs = vec!["in".to_string()];
        g.nodes.push(fb);

        g.edges.push(KGEdge::control("par", "a", "fa", "in"));
        g.edges.push(KGEdge::control("par", "b", "fb", "in"));

        let prog = compile(&g);
        let kir = serializer::write(&prog);

        assert!(
            kir.contains("parallel("),
            "expected parallel statement, got:\n{kir}"
        );
        assert!(kir.contains("par_a"), "expected par_a label, got:\n{kir}");
        assert!(kir.contains("par_b"), "expected par_b label, got:\n{kir}");
    }

    /// JSON roundtrip of KirGraph does not affect compilation output.
    #[test]
    fn test_compile_after_json_roundtrip() {
        let mut g = KirGraph::default();
        g.nodes.push(value_node("v1", 99));
        g.nodes.push(func_node("p1", "print", vec!["x"], vec![]));
        g.edges.push(KGEdge::data("v1", "value", "p1", "x"));

        let json = g.to_json();
        let g2 = KirGraph::from_json(&json).expect("roundtrip failed");

        let kir1 = serializer::write(&compile(&g));
        let kir2 = serializer::write(&compile(&g2));
        assert_eq!(
            kir1, kir2,
            "compilation must be stable after JSON roundtrip"
        );
    }
}
