//! Graph extraction: converts KIR source text into a [`KirGraph`].
//!
//! Port of `kohakunode/layout/ascii_view.py` — the `_GraphBuilder` class.

pub mod auto_layout;
pub mod optimizer;
pub mod score;

#[cfg(feature = "pyo3")]
pub mod pyo3;

use std::collections::{HashMap, HashSet};

use crate::ast::{
    Assignment, Branch, DataflowBlock, Expression, FuncCall, Parallel, Statement, Switch, Value,
};
use crate::kirgraph::{KGEdge, KGNode, KGPort, KirGraph};
use crate::parser::parse;

// ---------------------------------------------------------------------------
// Metadata helpers
// ---------------------------------------------------------------------------

fn meta_id(metadata: &Option<Vec<crate::ast::MetaAnnotation>>) -> Option<String> {
    let meta = metadata.as_ref()?;
    for m in meta {
        if let Some(Value::Str(s)) = m.data.get("node_id") {
            return Some(s.clone());
        }
    }
    None
}

fn meta_pos(metadata: &Option<Vec<crate::ast::MetaAnnotation>>) -> [i64; 2] {
    if let Some(meta) = metadata.as_ref() {
        for m in meta {
            if let Some(val) = m.data.get("pos") {
                match val {
                    Value::List(v) if v.len() >= 2 => {
                        let x = match &v[0] {
                            Value::Int(i) => *i,
                            Value::Float(f) => *f as i64,
                            _ => 0,
                        };
                        let y = match &v[1] {
                            Value::Int(i) => *i,
                            Value::Float(f) => *f as i64,
                            _ => 0,
                        };
                        return [x, y];
                    }
                    _ => {}
                }
            }
        }
    }
    [0, 0]
}

// ---------------------------------------------------------------------------
// GraphBuilder
// ---------------------------------------------------------------------------

struct GraphBuilder {
    nodes: Vec<KGNode>,
    edges: Vec<KGEdge>,
    node_counter: u32,
    /// var_name -> (node_id, port_name)
    var_source: HashMap<String, (String, String)>,
    /// namespace_label -> first node id inside that namespace
    ns_first_node: HashMap<String, Option<String>>,
    /// jump targets: (from_ctrl_id, from_port, target_label)
    jump_wires: Vec<(Option<String>, String, String)>,
    /// Deferred ctrl edges: (from_nid, from_port) awaiting next node
    deferred_ctrl_out: Vec<(String, String)>,
    /// Track namespaces already walked by Branch/Switch handlers
    walked_ns: HashSet<String>,
    /// Merge metadata from Jump statements: ns_label -> (node_id, pos)
    merge_meta: HashMap<String, (String, [i64; 2])>,
}

impl GraphBuilder {
    fn new() -> Self {
        Self {
            nodes: Vec::new(),
            edges: Vec::new(),
            node_counter: 0,
            var_source: HashMap::new(),
            ns_first_node: HashMap::new(),
            jump_wires: Vec::new(),
            deferred_ctrl_out: Vec::new(),
            walked_ns: HashSet::new(),
            merge_meta: HashMap::new(),
        }
    }

    fn build(mut self, stmts: &[Statement]) -> KirGraph {
        self.walk(stmts, None, false, None, "out");
        self.resolve_jump_wires();
        synthesize_merge_nodes(
            &mut self.nodes,
            &mut self.edges,
            &self.merge_meta,
            &self.ns_first_node,
        );
        KirGraph {
            nodes: self.nodes,
            edges: self.edges,
            ..KirGraph::default()
        }
    }

    // ------------------------------------------------------------------
    // ID generation
    // ------------------------------------------------------------------

    fn gen_id(&mut self, prefix: &str) -> String {
        self.node_counter += 1;
        format!("{}_{}", prefix, self.node_counter)
    }

    // ------------------------------------------------------------------
    // Edge helpers
    // ------------------------------------------------------------------

    fn ctrl_edge(&mut self, from_id: &str, from_port: &str, to_id: &str, to_port: &str) {
        self.edges
            .push(KGEdge::control(from_id, from_port, to_id, to_port));
    }

    fn wire_deferred(&mut self, to_nid: &str) {
        let deferred = std::mem::take(&mut self.deferred_ctrl_out);
        for (f_nid, f_port) in deferred {
            self.ctrl_edge(&f_nid, &f_port, to_nid, "in");
        }
    }

    // ------------------------------------------------------------------
    // Data edge helpers
    // ------------------------------------------------------------------

    fn wire_data_inputs(&mut self, inputs: &[Expression], nid: &str, d_in: &[KGPort]) {
        for (i, inp) in inputs.iter().enumerate() {
            let var_name = match inp {
                Expression::Identifier(id) => Some(id.name.clone()),
                Expression::KeywordArg(kw) => {
                    if let Expression::Identifier(id) = kw.value.as_ref() {
                        Some(id.name.clone())
                    } else {
                        None
                    }
                }
                _ => None,
            };
            if let Some(vname) = var_name {
                if let Some((src_nid, src_port)) = self.var_source.get(&vname).cloned() {
                    let to_port = if i < d_in.len() {
                        d_in[i].port.clone()
                    } else {
                        format!("in_{}", i)
                    };
                    self.edges
                        .push(KGEdge::data(&src_nid, &src_port, nid, &to_port));
                }
            }
        }
    }

    fn wire_condition(&mut self, condition: &Expression, nid: &str, port: &str) {
        if let Expression::Identifier(id) = condition {
            if let Some((src_nid, src_port)) = self.var_source.get(&id.name).cloned() {
                self.edges
                    .push(KGEdge::data(&src_nid, &src_port, nid, port));
            }
        }
    }

    // ------------------------------------------------------------------
    // Node creation
    // ------------------------------------------------------------------

    fn make_func_node(&mut self, stmt: &FuncCall) -> String {
        let nid = meta_id(&stmt.metadata).unwrap_or_else(|| self.gen_id(&stmt.func_name));
        let pos = meta_pos(&stmt.metadata);

        let mut d_in: Vec<KGPort> = Vec::new();
        for (i, inp) in stmt.inputs.iter().enumerate() {
            let pname;
            let default;
            match inp {
                Expression::KeywordArg(kw) => {
                    pname = kw.name.clone();
                    default = if let Expression::Literal(lit) = kw.value.as_ref() {
                        Some(lit.value.clone())
                    } else {
                        None
                    };
                }
                Expression::Literal(lit) => {
                    pname = format!("in_{}", i);
                    default = Some(lit.value.clone());
                }
                _ => {
                    pname = format!("in_{}", i);
                    default = None;
                }
            }
            if let Some(def) = default {
                d_in.push(KGPort::with_default(pname, def));
            } else {
                d_in.push(KGPort::new(pname));
            }
        }

        // Strip {node_id}_ prefix from output port names to keep them clean
        let prefix = format!("{}_", nid);
        let d_out: Vec<KGPort> = stmt
            .outputs
            .iter()
            .filter_map(|o| {
                let s = match o {
                    crate::ast::OutputTarget::Name(n) => n.clone(),
                    crate::ast::OutputTarget::Wildcard => "_".to_string(),
                };
                if s == "_" {
                    return None;
                }
                let port_name = if s.starts_with(&prefix) {
                    s[prefix.len()..].to_string()
                } else {
                    s
                };
                Some(KGPort::new(port_name))
            })
            .collect();

        let mut meta = HashMap::new();
        meta.insert(
            "pos".to_string(),
            Value::List(vec![Value::Int(pos[0]), Value::Int(pos[1])]),
        );

        self.nodes.push(KGNode {
            id: nid.clone(),
            r#type: stmt.func_name.clone(),
            name: stmt.func_name.clone(),
            data_inputs: d_in.clone(),
            data_outputs: d_out.clone(),
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs: vec!["out".to_string()],
            properties: HashMap::new(),
            meta,
        });

        self.wire_data_inputs(&stmt.inputs, &nid, &d_in);

        for o in &stmt.outputs {
            if let crate::ast::OutputTarget::Name(n) = o {
                if n != "_" {
                    let port_name = if n.starts_with(&prefix) {
                        n[prefix.len()..].to_string()
                    } else {
                        n.clone()
                    };
                    self.var_source.insert(n.clone(), (nid.clone(), port_name));
                }
            }
        }

        nid
    }

    // ------------------------------------------------------------------
    // Statement handlers
    // ------------------------------------------------------------------

    fn handle_assignment(
        &mut self,
        stmt: &Assignment,
        first_node_in_scope: Option<String>,
    ) -> Option<String> {
        // If the RHS is an identifier we already know, just alias the variable.
        // This handles feedback initialization like `add_5_counter = value_3_value`.
        if let Expression::Identifier(ident) = &stmt.value {
            if let Some(source) = self.var_source.get(&ident.name).cloned() {
                self.var_source.insert(stmt.target.clone(), source);
                return first_node_in_scope;
            }
        }

        let nid = meta_id(&stmt.metadata).unwrap_or_else(|| self.gen_id("value"));
        let pos = meta_pos(&stmt.metadata);

        let val = if let Expression::Literal(lit) = &stmt.value {
            Some(lit.value.clone())
        } else {
            None
        };

        let mut meta = HashMap::new();
        meta.insert(
            "pos".to_string(),
            Value::List(vec![Value::Int(pos[0]), Value::Int(pos[1])]),
        );

        let mut props = HashMap::new();
        if let Some(v) = val {
            props.insert("value".to_string(), v);
        }

        self.nodes.push(KGNode {
            id: nid.clone(),
            r#type: "value".to_string(),
            name: stmt.target.clone(),
            data_inputs: vec![],
            data_outputs: vec![KGPort::new("value")],
            ctrl_inputs: vec![],
            ctrl_outputs: vec![],
            properties: props,
            meta,
        });
        self.var_source
            .insert(stmt.target.clone(), (nid.clone(), "value".to_string()));

        if first_node_in_scope.is_none() {
            Some(nid)
        } else {
            first_node_in_scope
        }
    }

    fn handle_funccall(
        &mut self,
        stmt: &FuncCall,
        in_dataflow: bool,
        first_node_in_scope: Option<String>,
        last_ctrl: Option<String>,
        prev_ctrl: Option<&str>,
        ctrl_out_port: &str,
        used_initial_port: &mut bool,
    ) -> (Option<String>, Option<String>) {
        let nid = self.make_func_node(stmt);
        let first = if first_node_in_scope.is_none() {
            Some(nid.clone())
        } else {
            first_node_in_scope
        };
        if !in_dataflow {
            if let Some(ref lc) = last_ctrl {
                let from_port = get_from_port(lc, prev_ctrl, ctrl_out_port, used_initial_port);
                self.ctrl_edge(lc, &from_port, &nid, "in");
            }
            self.wire_deferred(&nid);
            (first, Some(nid))
        } else {
            (first, last_ctrl)
        }
    }

    fn handle_branch(
        &mut self,
        stmt: &Branch,
        stmts: &[Statement],
        first_node_in_scope: Option<String>,
        last_ctrl: Option<String>,
        prev_ctrl: Option<&str>,
        ctrl_out_port: &str,
        used_initial_port: &mut bool,
    ) -> (Option<String>, Option<String>) {
        let nid = meta_id(&stmt.metadata).unwrap_or_else(|| self.gen_id("branch"));
        let pos = meta_pos(&stmt.metadata);

        let mut meta = HashMap::new();
        meta.insert(
            "pos".to_string(),
            Value::List(vec![Value::Int(pos[0]), Value::Int(pos[1])]),
        );

        self.nodes.push(KGNode {
            id: nid.clone(),
            r#type: "branch".to_string(),
            name: "Branch".to_string(),
            data_inputs: vec![KGPort::with_type("condition", "bool")],
            data_outputs: vec![],
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs: vec!["true".to_string(), "false".to_string()],
            properties: HashMap::new(),
            meta,
        });

        self.wire_condition(&stmt.condition, &nid, "condition");

        if let Some(ref lc) = last_ctrl {
            let from_port = get_from_port(lc, prev_ctrl, ctrl_out_port, used_initial_port);
            self.ctrl_edge(lc, &from_port, &nid, "in");
        }
        self.wire_deferred(&nid);

        let first = if first_node_in_scope.is_none() {
            Some(nid.clone())
        } else {
            first_node_in_scope
        };

        // Walk true/false branches
        for s in stmts {
            if let Statement::Namespace(ns) = s {
                if ns.name == stmt.true_label {
                    self.walked_ns.insert(ns.name.clone());
                    self.walk(&ns.body, Some(&nid), false, Some(&ns.name), "true");
                    if ns.body.is_empty() {
                        self.deferred_ctrl_out
                            .push((nid.clone(), "true".to_string()));
                    }
                } else if ns.name == stmt.false_label {
                    self.walked_ns.insert(ns.name.clone());
                    self.walk(&ns.body, Some(&nid), false, Some(&ns.name), "false");
                    if ns.body.is_empty() {
                        self.deferred_ctrl_out
                            .push((nid.clone(), "false".to_string()));
                    }
                }
            }
        }

        (first, None)
    }

    fn handle_switch(
        &mut self,
        stmt: &Switch,
        stmts: &[Statement],
        first_node_in_scope: Option<String>,
        last_ctrl: Option<String>,
        prev_ctrl: Option<&str>,
        ctrl_out_port: &str,
        used_initial_port: &mut bool,
    ) -> (Option<String>, Option<String>) {
        let nid = meta_id(&stmt.metadata).unwrap_or_else(|| self.gen_id("switch"));
        let pos = meta_pos(&stmt.metadata);

        let cout: Vec<String> = stmt.cases.iter().map(|(_, label)| label.clone()).collect();
        let mut cout_with_default = cout.clone();
        let mut case_map: HashMap<String, Value> = HashMap::new();
        for (case_expr, label) in &stmt.cases {
            let val = match case_expr {
                Expression::Literal(lit) => lit.value.clone(),
                _ => Value::Str(format!("{:?}", case_expr)),
            };
            case_map.insert(label.clone(), val);
        }
        if let Some(dl) = &stmt.default_label {
            cout_with_default.push(dl.clone());
            case_map.insert(dl.clone(), Value::Str("_default_".to_string()));
        }

        let mut meta = HashMap::new();
        meta.insert(
            "pos".to_string(),
            Value::List(vec![Value::Int(pos[0]), Value::Int(pos[1])]),
        );

        let mut props = HashMap::new();
        props.insert("cases".to_string(), Value::Dict(case_map));

        self.nodes.push(KGNode {
            id: nid.clone(),
            r#type: "switch".to_string(),
            name: "Switch".to_string(),
            data_inputs: vec![KGPort::new("value")],
            data_outputs: vec![],
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs: cout_with_default,
            properties: props,
            meta,
        });

        self.wire_condition(&stmt.value, &nid, "value");

        if let Some(ref lc) = last_ctrl {
            let from_port = get_from_port(lc, prev_ctrl, ctrl_out_port, used_initial_port);
            self.ctrl_edge(lc, &from_port, &nid, "in");
        }
        self.wire_deferred(&nid);

        let first = if first_node_in_scope.is_none() {
            Some(nid.clone())
        } else {
            first_node_in_scope
        };

        // Walk case branches
        for s in stmts {
            if let Statement::Namespace(ns) = s {
                for (_, label) in &stmt.cases {
                    if ns.name == *label {
                        self.walked_ns.insert(ns.name.clone());
                        self.walk(&ns.body, Some(&nid), false, Some(&ns.name), label);
                        if ns.body.is_empty() {
                            self.deferred_ctrl_out.push((nid.clone(), label.clone()));
                        }
                    }
                }
                if let Some(dl) = &stmt.default_label {
                    if ns.name == *dl {
                        self.walked_ns.insert(ns.name.clone());
                        self.walk(&ns.body, Some(&nid), false, Some(&ns.name), dl);
                        if ns.body.is_empty() {
                            self.deferred_ctrl_out.push((nid.clone(), dl.clone()));
                        }
                    }
                }
            }
        }

        (first, None)
    }

    fn handle_parallel(
        &mut self,
        stmt: &Parallel,
        stmts: &[Statement],
        first_node_in_scope: Option<String>,
        last_ctrl: Option<String>,
        prev_ctrl: Option<&str>,
        ctrl_out_port: &str,
        used_initial_port: &mut bool,
    ) -> (Option<String>, Option<String>) {
        let nid = meta_id(&stmt.metadata).unwrap_or_else(|| self.gen_id("parallel"));
        let pos = meta_pos(&stmt.metadata);

        let mut meta = HashMap::new();
        meta.insert(
            "pos".to_string(),
            Value::List(vec![Value::Int(pos[0]), Value::Int(pos[1])]),
        );

        self.nodes.push(KGNode {
            id: nid.clone(),
            r#type: "parallel".to_string(),
            name: "Parallel".to_string(),
            data_inputs: vec![],
            data_outputs: vec![],
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs: stmt.labels.clone(),
            properties: HashMap::new(),
            meta,
        });

        if let Some(ref lc) = last_ctrl {
            let from_port = get_from_port(lc, prev_ctrl, ctrl_out_port, used_initial_port);
            self.ctrl_edge(lc, &from_port, &nid, "in");
        }
        self.wire_deferred(&nid);

        let first = if first_node_in_scope.is_none() {
            Some(nid.clone())
        } else {
            first_node_in_scope
        };

        for s in stmts {
            if let Statement::Namespace(ns) = s {
                if stmt.labels.contains(&ns.name) {
                    self.walked_ns.insert(ns.name.clone());
                    self.walk(
                        &ns.body,
                        Some(&nid),
                        false,
                        Some(&ns.name),
                        &ns.name.clone(),
                    );
                }
            }
        }

        (first, Some(nid))
    }

    fn handle_dataflow_block(
        &mut self,
        stmt: &DataflowBlock,
        first_node_in_scope: Option<String>,
        last_ctrl: Option<String>,
        prev_ctrl: Option<&str>,
        ctrl_out_port: &str,
        used_initial_port: &mut bool,
    ) -> (Option<String>, Option<String>) {
        let df_nodes_before = self.nodes.len();
        self.walk(&stmt.body, None, true, None, "out");
        let df_new_count = self.nodes.len() - df_nodes_before;

        if df_new_count == 0 {
            return (first_node_in_scope, last_ctrl);
        }

        let first_df = self.nodes[df_nodes_before].id.clone();
        let last_df = self.nodes[df_nodes_before + df_new_count - 1].id.clone();

        // Entry boundary: last_ctrl -> first node in block
        if let Some(ref lc) = last_ctrl {
            let from_port = get_from_port(lc, prev_ctrl, ctrl_out_port, used_initial_port);
            self.ctrl_edge(lc, &from_port, &first_df, "in");
        }
        // Wire any deferred ctrl to first df node
        let deferred = std::mem::take(&mut self.deferred_ctrl_out);
        for (f_nid, f_port) in deferred {
            self.ctrl_edge(&f_nid, &f_port, &first_df, "in");
        }

        // Chain all nodes in lexical order with ctrl pass-through edges
        let df_node_ids: Vec<String> = (df_nodes_before..df_nodes_before + df_new_count)
            .map(|i| self.nodes[i].id.clone())
            .collect();
        for i in 0..df_node_ids.len() - 1 {
            self.ctrl_edge(&df_node_ids[i], "out", &df_node_ids[i + 1], "in");
        }

        let first = if first_node_in_scope.is_none() {
            Some(first_df)
        } else {
            first_node_in_scope
        };
        (first, Some(last_df))
    }

    // ------------------------------------------------------------------
    // Main walker
    // ------------------------------------------------------------------

    /// Walk statements. Returns last ctrl node id.
    ///
    /// `prev_ctrl`: the ctrl node from which we enter this scope.
    /// `ctrl_out_port`: port name to use for the first ctrl edge FROM prev_ctrl.
    fn walk(
        &mut self,
        stmts: &[Statement],
        prev_ctrl: Option<&str>,
        in_dataflow: bool,
        ns_label: Option<&str>,
        ctrl_out_port: &str,
    ) -> Option<String> {
        let mut last_ctrl: Option<String> = prev_ctrl.map(|s| s.to_string());
        let mut first_node_in_scope: Option<String> = None;
        let mut used_initial_port = false;

        // We need to snapshot the initial value for the closure logic
        let prev_ctrl_owned = prev_ctrl.map(|s| s.to_string());

        for stmt in stmts {
            match stmt {
                Statement::Assignment(a) => {
                    first_node_in_scope = self.handle_assignment(a, first_node_in_scope.clone());
                }

                Statement::FuncCall(fc) => {
                    let (new_first, new_last) = self.handle_funccall(
                        fc,
                        in_dataflow,
                        first_node_in_scope.clone(),
                        last_ctrl.clone(),
                        prev_ctrl_owned.as_deref(),
                        ctrl_out_port,
                        &mut used_initial_port,
                    );
                    first_node_in_scope = new_first;
                    last_ctrl = new_last;
                }

                Statement::Branch(b) => {
                    let (new_first, new_last) = self.handle_branch(
                        b,
                        stmts,
                        first_node_in_scope.clone(),
                        last_ctrl.clone(),
                        prev_ctrl_owned.as_deref(),
                        ctrl_out_port,
                        &mut used_initial_port,
                    );
                    first_node_in_scope = new_first;
                    last_ctrl = new_last;
                }

                Statement::Switch(sw) => {
                    let (new_first, new_last) = self.handle_switch(
                        sw,
                        stmts,
                        first_node_in_scope.clone(),
                        last_ctrl.clone(),
                        prev_ctrl_owned.as_deref(),
                        ctrl_out_port,
                        &mut used_initial_port,
                    );
                    first_node_in_scope = new_first;
                    last_ctrl = new_last;
                }

                Statement::Parallel(p) => {
                    let (new_first, new_last) = self.handle_parallel(
                        p,
                        stmts,
                        first_node_in_scope.clone(),
                        last_ctrl.clone(),
                        prev_ctrl_owned.as_deref(),
                        ctrl_out_port,
                        &mut used_initial_port,
                    );
                    first_node_in_scope = new_first;
                    last_ctrl = new_last;
                }

                Statement::Jump(j) => {
                    let port = if !used_initial_port
                        && last_ctrl.as_deref() == prev_ctrl_owned.as_deref()
                    {
                        used_initial_port = true;
                        ctrl_out_port.to_string()
                    } else {
                        "out".to_string()
                    };
                    self.jump_wires
                        .push((last_ctrl.clone(), port, j.target.clone()));
                    // Save @meta from jump (carries merge node position)
                    if let Some(nid) = meta_id(&j.metadata) {
                        let pos = meta_pos(&j.metadata);
                        self.merge_meta.insert(j.target.clone(), (nid, pos));
                    }
                    last_ctrl = None;
                }

                Statement::Namespace(ns) => {
                    if !self.ns_first_node.contains_key(&ns.name)
                        && !self.walked_ns.contains(&ns.name)
                    {
                        self.walked_ns.insert(ns.name.clone());
                        let ns_last = self.walk(
                            &ns.body,
                            last_ctrl.as_deref(),
                            in_dataflow,
                            Some(&ns.name),
                            "out",
                        );
                        if ns_last.is_some() {
                            last_ctrl = ns_last;
                        }
                    }
                }

                Statement::DataflowBlock(df) => {
                    let (new_first, new_last) = self.handle_dataflow_block(
                        df,
                        first_node_in_scope.clone(),
                        last_ctrl.clone(),
                        prev_ctrl_owned.as_deref(),
                        ctrl_out_port,
                        &mut used_initial_port,
                    );
                    first_node_in_scope = new_first;
                    last_ctrl = new_last;
                }

                _ => {}
            }
        }

        if let Some(label) = ns_label {
            if first_node_in_scope.is_some() {
                self.ns_first_node
                    .insert(label.to_string(), first_node_in_scope.clone());
            }
        }

        last_ctrl
    }

    // ------------------------------------------------------------------
    // Post-processing
    // ------------------------------------------------------------------

    fn resolve_jump_wires(&mut self) {
        let jump_wires = std::mem::take(&mut self.jump_wires);
        let mut new_entry_nodes: Vec<KGNode> = Vec::new();
        let mut new_entry_edges: Vec<KGEdge> = Vec::new();

        for (from_id, from_port, target_label) in &jump_wires {
            let target_first = match self.ns_first_node.get(target_label) {
                Some(Some(s)) => s.clone(),
                _ => continue,
            };
            if let Some(fid) = from_id {
                self.ctrl_edge(fid, from_port, &target_first, "in");
            } else {
                // Jump from nowhere: create synthetic entry node
                self.node_counter += 1;
                let entry_id = format!("entry_{}", self.node_counter);
                let mut meta = HashMap::new();
                meta.insert(
                    "pos".to_string(),
                    Value::List(vec![Value::Int(0), Value::Int(0)]),
                );
                new_entry_nodes.push(KGNode {
                    id: entry_id.clone(),
                    r#type: "value".to_string(),
                    name: "_entry".to_string(),
                    data_inputs: vec![],
                    data_outputs: vec![],
                    ctrl_inputs: vec![],
                    ctrl_outputs: vec!["out".to_string()],
                    properties: HashMap::new(),
                    meta,
                });
                new_entry_edges.push(KGEdge::control(&entry_id, "out", &target_first, "in"));
            }
        }

        self.nodes.extend(new_entry_nodes);
        self.edges.extend(new_entry_edges);
    }
}

// ---------------------------------------------------------------------------
// Helper: get_from_port (mirrors the Python closure logic)
// ---------------------------------------------------------------------------

fn get_from_port(
    last_ctrl: &str,
    prev_ctrl: Option<&str>,
    ctrl_out_port: &str,
    used_initial_port: &mut bool,
) -> String {
    if !*used_initial_port && Some(last_ctrl) == prev_ctrl {
        *used_initial_port = true;
        ctrl_out_port.to_string()
    } else {
        "out".to_string()
    }
}

// ---------------------------------------------------------------------------
// Merge node synthesis
// ---------------------------------------------------------------------------

fn synthesize_merge_nodes(
    nodes: &mut Vec<KGNode>,
    edges: &mut Vec<KGEdge>,
    merge_meta: &HashMap<String, (String, [i64; 2])>,
    ns_first_node: &HashMap<String, Option<String>>,
) {
    let mut node_counter = 0u32;
    let mut gen_id = || {
        node_counter += 1;
        format!("merge_{}", node_counter)
    };

    // Reverse map: first_node_in_ns -> ns_label
    let first_to_ns: HashMap<&str, &str> = ns_first_node
        .iter()
        .filter_map(|(k, v)| v.as_deref().map(|v| (v, k.as_str())))
        .collect();

    // Find all nodes with 2+ incoming ctrl edges
    let mut incoming_ctrl: HashMap<String, Vec<usize>> = HashMap::new();
    for (i, e) in edges.iter().enumerate() {
        if e.r#type == "control" {
            incoming_ctrl.entry(e.to_node.clone()).or_default().push(i);
        }
    }

    let mut new_nodes: Vec<KGNode> = Vec::new();
    let mut new_edges: Vec<KGEdge> = Vec::new();

    for (target_nid, edge_indices) in &incoming_ctrl {
        if edge_indices.len() < 2 {
            continue;
        }

        // Check if we have saved @meta for this merge
        let ns_label = first_to_ns.get(target_nid.as_str());
        let meta_info = ns_label.and_then(|ns| merge_meta.get(*ns));

        let merge_nid = if let Some((nid, _)) = meta_info {
            nid.clone()
        } else {
            gen_id()
        };
        let pos = if let Some((_, p)) = meta_info {
            *p
        } else {
            [0, 0]
        };

        let n_inputs = edge_indices.len();
        let merge_inputs: Vec<String> = (0..n_inputs).map(|i| format!("in_{}", i)).collect();

        let mut meta = HashMap::new();
        meta.insert(
            "pos".to_string(),
            Value::List(vec![Value::Int(pos[0]), Value::Int(pos[1])]),
        );

        new_nodes.push(KGNode {
            id: merge_nid.clone(),
            r#type: "merge".to_string(),
            name: "Merge".to_string(),
            data_inputs: vec![],
            data_outputs: vec![],
            ctrl_inputs: merge_inputs.clone(),
            ctrl_outputs: vec!["out".to_string()],
            properties: HashMap::new(),
            meta,
        });

        for (i, &ei) in edge_indices.iter().enumerate() {
            let old = &edges[ei];
            let from_node = old.from_node.clone();
            let from_port = old.from_port.clone();
            // We'll mark the edge index for replacement
            new_edges.push(KGEdge::control(
                &from_node,
                &from_port,
                &merge_nid,
                &merge_inputs[i],
            ));
            // Mark as replaced by storing sentinel — we'll handle in final step
        }

        // Add merge -> target edge
        new_edges.push(KGEdge::control(&merge_nid, "out", target_nid, "in"));
    }

    // Now apply replacements: for each target with 2+ incoming, replace those edges
    // We need to rebuild edges, replacing indexed edges with new merge edges
    let mut replaced: HashSet<usize> = HashSet::new();

    // Collect which indices to replace per target
    let mut replacement_map: HashMap<usize, KGEdge> = HashMap::new();
    let mut merge_node_index = 0usize;

    for (target_nid, edge_indices) in &incoming_ctrl {
        if edge_indices.len() < 2 {
            continue;
        }
        // The merge_nid for this target: find it from new_nodes by matching
        // We need to track this systematically
        let _ = target_nid;
        for &ei in edge_indices {
            replaced.insert(ei);
        }
        // new_edges has them in order — merge_node_index tracks position in the batch
        // Each target produces n_inputs + 1 new edges (n to merge, 1 merge-to-target)
        let n_inputs = edge_indices.len();
        for (i, &ei) in edge_indices.iter().enumerate() {
            replacement_map.insert(ei, new_edges[merge_node_index + i].clone());
        }
        merge_node_index += n_inputs + 1; // n input edges + 1 output edge
    }

    // Rebuild edges: keep non-replaced, replace replaced ones with their merge-input versions
    let mut final_edges: Vec<KGEdge> = Vec::new();
    for (i, e) in edges.iter().enumerate() {
        if let Some(replacement) = replacement_map.get(&i) {
            final_edges.push(replacement.clone());
        } else {
            final_edges.push(e.clone());
        }
    }

    // Add merge-to-target edges (every (n_inputs+1)th in new_edges batches)
    let mut idx = 0;
    for (_, edge_indices) in &incoming_ctrl {
        if edge_indices.len() < 2 {
            continue;
        }
        let n_inputs = edge_indices.len();
        // The last edge in this batch is the merge->target edge
        final_edges.push(new_edges[idx + n_inputs].clone());
        idx += n_inputs + 1;
    }

    *edges = final_edges;
    nodes.extend(new_nodes);
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Parse KIR source and extract nodes + edges directly from the AST.
pub fn kir_to_graph(source: &str) -> Result<KirGraph, crate::parser::ParseError> {
    let prog = parse(source)?;
    Ok(GraphBuilder::new().build(&prog.body))
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // SIMPLE_KIR: two chained function calls (sequential ctrl flow)
    const SIMPLE_KIR: &str = r#"
()init(x)
(x)print()
"#;

    // BRANCH_KIR: branch where both arms jump to a merge target
    const BRANCH_KIR: &str = r#"
flag = true
(flag)branch(`yes`, `no`)
yes:
    ()jump(`done`)
no:
    ()jump(`done`)
done:
    ()noop()
"#;

    const DATAFLOW_KIR: &str = r#"
@dataflow:
    (1)add(a)
    (2)add(b)
"#;

    #[test]
    fn test_simple_kir_to_graph() {
        let graph = kir_to_graph(SIMPLE_KIR).expect("parse failed");
        // Should have: init node and print node
        assert!(
            graph.nodes.len() >= 2,
            "expected at least 2 nodes, got {}",
            graph.nodes.len()
        );
        let types: Vec<&str> = graph.nodes.iter().map(|n| n.r#type.as_str()).collect();
        assert!(types.contains(&"init"), "expected init node");
        assert!(types.contains(&"print"), "expected print node");
    }

    #[test]
    fn test_simple_kir_has_data_edge() {
        let graph = kir_to_graph(SIMPLE_KIR).expect("parse failed");
        let data_edges: Vec<&KGEdge> = graph.edges.iter().filter(|e| e.r#type == "data").collect();
        assert!(!data_edges.is_empty(), "expected data edge from x to print");
    }

    #[test]
    fn test_simple_kir_has_ctrl_edge() {
        let graph = kir_to_graph(SIMPLE_KIR).expect("parse failed");
        let ctrl_edges: Vec<&KGEdge> = graph
            .edges
            .iter()
            .filter(|e| e.r#type == "control")
            .collect();
        assert!(!ctrl_edges.is_empty(), "expected control edge");
    }

    #[test]
    fn test_branch_kir_has_branch_node() {
        let graph = kir_to_graph(BRANCH_KIR).expect("parse failed");
        let branch_nodes: Vec<&KGNode> = graph
            .nodes
            .iter()
            .filter(|n| n.r#type == "branch")
            .collect();
        assert_eq!(branch_nodes.len(), 1, "expected 1 branch node");
        let b = branch_nodes[0];
        assert!(b.ctrl_outputs.contains(&"true".to_string()));
        assert!(b.ctrl_outputs.contains(&"false".to_string()));
    }

    #[test]
    fn test_branch_kir_has_merge_node() {
        let graph = kir_to_graph(BRANCH_KIR).expect("parse failed");
        let merge_nodes: Vec<&KGNode> =
            graph.nodes.iter().filter(|n| n.r#type == "merge").collect();
        // noop node gets 2 incoming ctrl edges (true + false from branch), so a merge is inserted
        assert!(!merge_nodes.is_empty(), "expected at least 1 merge node");
    }

    #[test]
    fn test_dataflow_block_has_ctrl_chain() {
        let graph = kir_to_graph(DATAFLOW_KIR).expect("parse failed");
        // add_1 and add_2 should be connected by a ctrl edge (pass-through chain)
        let ctrl_edges: Vec<&KGEdge> = graph
            .edges
            .iter()
            .filter(|e| e.r#type == "control")
            .collect();
        assert!(
            !ctrl_edges.is_empty(),
            "expected ctrl chain in dataflow block"
        );
    }

    #[test]
    fn test_mixed_mode_kir() {
        let source = include_str!("../../../../examples/kir_basics/mixed_mode.kir");
        let graph = kir_to_graph(source).expect("parse failed");
        assert!(
            !graph.nodes.is_empty(),
            "expected nodes from mixed_mode.kir"
        );
        assert!(
            !graph.edges.is_empty(),
            "expected edges from mixed_mode.kir"
        );
        // Verify we have branch and merge nodes
        let has_branch = graph.nodes.iter().any(|n| n.r#type == "branch");
        assert!(has_branch, "expected branch node in mixed_mode.kir");
    }

    #[test]
    fn test_node_ids_unique() {
        let source = include_str!("../../../../examples/kir_basics/mixed_mode.kir");
        let graph = kir_to_graph(source).expect("parse failed");
        let ids: Vec<&str> = graph.nodes.iter().map(|n| n.id.as_str()).collect();
        let id_set: HashSet<&&str> = ids.iter().collect();
        assert_eq!(ids.len(), id_set.len(), "node IDs must be unique");
    }
}
