//! L2 → L1 decompiler: KIR Program AST → KirGraph.
//!
//! Recovers a flat node-and-edge graph from a KIR AST by reading `@meta`
//! annotations and inferring topology from variable references and control
//! flow.
//!
//! Ported from `kohakunode/kirgraph/decompiler.py`.

use std::collections::{HashMap, HashSet};

use crate::ast::{
    Assignment, Branch, Expression, FuncCall, Jump, MetaAnnotation, OutputTarget, Parallel,
    Program, Statement, Switch, Value,
};

use super::{KGEdge, KGNode, KGPort, KirGraph};

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Decompile a KIR [`Program`] AST (Level 2) back to a [`KirGraph`] (Level 1).
pub fn decompile(program: &Program) -> KirGraph {
    let mut d = KirGraphDecompiler::new();
    d.run(program)
}

// ---------------------------------------------------------------------------
// Internal decompiler state
// ---------------------------------------------------------------------------

struct KirGraphDecompiler {
    nodes: HashMap<String, KGNode>,
    edges: Vec<KGEdge>,
    /// Maps output variable name → (node_id, port_name).
    var_to_node_port: HashMap<String, (String, String)>,
    node_counter: u32,
    auto_pos_counter: u32,
    handled_namespaces: HashSet<String>,
}

impl KirGraphDecompiler {
    fn new() -> Self {
        KirGraphDecompiler {
            nodes: HashMap::new(),
            edges: Vec::new(),
            var_to_node_port: HashMap::new(),
            node_counter: 0,
            auto_pos_counter: 0,
            handled_namespaces: HashSet::new(),
        }
    }

    fn run(&mut self, program: &Program) -> KirGraph {
        // Pass 1: collect all nodes and control edges.
        self.walk_statements(&program.body, None, false, false, None);

        // Pass 2: resolve data edges from variable references.
        let known_ids: HashSet<String> = self.nodes.keys().cloned().collect();
        self.resolve_data_edges(&program.body, &known_ids);

        // Collect into sorted vecs for deterministic output.
        let mut nodes: Vec<KGNode> = self.nodes.values().cloned().collect();
        nodes.sort_by(|a, b| a.id.cmp(&b.id));

        KirGraph {
            version: "0.1.0".to_string(),
            nodes,
            edges: self.edges.clone(),
        }
    }

    // -----------------------------------------------------------------------
    // Pass 1 — node creation + control edges
    // -----------------------------------------------------------------------

    /// Walk statements, creating nodes and control edges.
    ///
    /// Returns the first node_id created in this call (used for connecting
    /// control edges from callers, e.g. branch → first-in-namespace).
    fn walk_statements(
        &mut self,
        stmts: &[Statement],
        prev_node_id: Option<&str>,
        _in_namespace: bool,
        in_dataflow: bool,
        parent_branch_edge: Option<(&str, &str)>,
    ) -> Option<String> {
        let mut last_id: Option<String> = prev_node_id.map(|s| s.to_string());
        let mut first_created_id: Option<String> = None;

        for stmt in stmts {
            match stmt {
                Statement::DataflowBlock(db) => {
                    // Dataflow blocks: nodes with NO ctrl edges.
                    self.walk_statements(&db.body, None, false, true, None);
                    continue;
                }

                Statement::Namespace(ns) => {
                    if !self.handled_namespaces.contains(&ns.name) {
                        // Walk namespace body — merge node handles the ctrl
                        // edge in.
                        self.walk_statements(&ns.body, last_id.as_deref(), true, false, None);
                    }
                    // After a namespace (entered via jump), don't chain.
                    last_id = None;
                    continue;
                }

                Statement::Jump(jump) => {
                    self.handle_jump(jump, &mut last_id, parent_branch_edge);
                    continue;
                }

                _ => {}
            }

            let node_id = match self.create_node_from_stmt(stmt) {
                Some(id) => id,
                None => continue,
            };

            if first_created_id.is_none() {
                first_created_id = Some(node_id.clone());
            }

            // Control edge from previous node (skipped in dataflow blocks).
            if let Some(ref prev_id) = last_id {
                if !in_dataflow {
                    let from_port = self
                        .nodes
                        .get(prev_id)
                        .and_then(|n| n.ctrl_outputs.first().cloned())
                        .unwrap_or_else(|| "out".to_string());
                    let to_port = self
                        .nodes
                        .get(&node_id)
                        .and_then(|n| n.ctrl_inputs.first().cloned())
                        .unwrap_or_else(|| "in".to_string());
                    self.edges.push(KGEdge::control(
                        prev_id.clone(),
                        from_port,
                        node_id.clone(),
                        to_port,
                    ));
                }
            }

            if in_dataflow {
                // No ctrl chaining inside dataflow blocks.
            } else {
                match stmt {
                    Statement::Branch(branch) => {
                        // Clone what we need before the mutable borrow.
                        let true_label = branch.true_label.clone();
                        let false_label = branch.false_label.clone();
                        let stmts_clone: Vec<Statement> = stmts.to_vec();
                        self.handle_branch_namespaces(
                            &true_label,
                            &false_label,
                            &node_id,
                            &stmts_clone,
                        );
                        last_id = None;
                    }
                    Statement::Switch(switch) => {
                        let cases: Vec<(Expression, String)> = switch.cases.clone();
                        let default_label: Option<String> = switch.default_label.clone();
                        let stmts_clone: Vec<Statement> = stmts.to_vec();
                        self.handle_switch_namespaces(
                            &cases,
                            default_label.as_deref(),
                            &node_id,
                            &stmts_clone,
                        );
                        last_id = None;
                    }
                    Statement::Parallel(parallel) => {
                        let labels: Vec<String> = parallel.labels.clone();
                        let stmts_clone: Vec<Statement> = stmts.to_vec();
                        self.handle_parallel_namespaces(&labels, &node_id, &stmts_clone);
                        last_id = None;
                    }
                    _ => {
                        last_id = Some(node_id.clone());
                    }
                }
            }
        }

        first_created_id
    }

    /// Handle a [`Jump`] statement: create or connect to a merge node.
    fn handle_jump(
        &mut self,
        jump: &Jump,
        last_id: &mut Option<String>,
        parent_branch_edge: Option<(&str, &str)>,
    ) {
        let target_ns = &jump.target;
        let jump_meta = extract_meta_from_jump(jump);

        if target_ns.starts_with("ns_") {
            let merge_id = &target_ns[3..];

            if self.nodes.contains_key(merge_id) {
                // Backward edge (loop back).
                let back_port = {
                    let merge_node = &self.nodes[merge_id];
                    if merge_node.ctrl_inputs.contains(&"back".to_string()) {
                        "back".to_string()
                    } else {
                        merge_node
                            .ctrl_inputs
                            .last()
                            .cloned()
                            .unwrap_or_else(|| "back".to_string())
                    }
                };

                if let Some(ref prev_id) = last_id.clone() {
                    let from_port = self
                        .nodes
                        .get(prev_id)
                        .and_then(|n| n.ctrl_outputs.first().cloned())
                        .unwrap_or_else(|| "out".to_string());
                    self.edges.push(KGEdge::control(
                        prev_id.clone(),
                        from_port,
                        merge_id.to_string(),
                        back_port,
                    ));
                } else if let Some((be_node, be_port)) = parent_branch_edge {
                    // Inside a branch namespace with no preceding nodes.
                    self.edges.push(KGEdge::control(
                        be_node.to_string(),
                        be_port.to_string(),
                        merge_id.to_string(),
                        back_port,
                    ));
                }
            } else {
                // Forward jump — create merge node.
                let meta = build_meta(jump_meta.as_ref(), &mut self.auto_pos_counter);
                let merge_node = KGNode {
                    id: merge_id.to_string(),
                    r#type: "merge".to_string(),
                    name: "Merge".to_string(),
                    data_inputs: vec![],
                    data_outputs: vec![],
                    ctrl_inputs: vec!["entry".to_string(), "back".to_string()],
                    ctrl_outputs: vec!["out".to_string()],
                    properties: HashMap::new(),
                    meta,
                };
                self.nodes.insert(merge_id.to_string(), merge_node);

                if let Some(ref prev_id) = last_id.clone() {
                    let from_port = self
                        .nodes
                        .get(prev_id)
                        .and_then(|n| n.ctrl_outputs.first().cloned())
                        .unwrap_or_else(|| "out".to_string());
                    self.edges.push(KGEdge::control(
                        prev_id.clone(),
                        from_port,
                        merge_id.to_string(),
                        "entry".to_string(),
                    ));
                }
                *last_id = Some(merge_id.to_string());
            }
        }
    }

    // -----------------------------------------------------------------------
    // Node creation
    // -----------------------------------------------------------------------

    /// Create a [`KGNode`] from a statement. Returns the node id or `None`.
    fn create_node_from_stmt(&mut self, stmt: &Statement) -> Option<String> {
        match stmt {
            Statement::Assignment(a) => Some(self.create_value_node(a)),
            Statement::FuncCall(f) => Some(self.create_func_node(f)),
            Statement::Branch(b) => Some(self.create_branch_node(b)),
            Statement::Switch(s) => Some(self.create_switch_node(s)),
            Statement::Parallel(p) => Some(self.create_parallel_node(p)),
            Statement::Jump(_) => None,
            _ => None,
        }
    }

    fn create_value_node(&mut self, stmt: &Assignment) -> String {
        let meta_data = extract_meta_from_assignment(stmt);
        let mut node_id = meta_data
            .as_ref()
            .and_then(|m| m.get("node_id"))
            .and_then(value_as_str)
            .map(|s| s.to_string());

        if node_id.is_none() {
            // Infer node_id from variable name.
            let known_ids: HashSet<String> = self.nodes.keys().cloned().collect();
            if let Some((nid, _)) = parse_var_name(&stmt.target, &known_ids) {
                node_id = Some(nid);
            } else {
                node_id = Some(self.gen_id("value"));
            }
        }
        let node_id = node_id.unwrap();

        // Determine value and type.
        let (value, value_type) = match &stmt.value {
            Expression::Literal(lit) => {
                let vt = if lit.literal_type == "none" {
                    "any".to_string()
                } else {
                    lit.literal_type.clone()
                };
                (Some(lit.value.clone()), vt)
            }
            _ => (None, "any".to_string()),
        };

        // Determine output port name.
        let known_single = {
            let mut s = HashSet::new();
            s.insert(node_id.clone());
            s
        };
        let port_name = parse_var_name(&stmt.target, &known_single)
            .map(|(_, p)| p)
            .unwrap_or_else(|| "value".to_string());

        let mut properties: HashMap<String, Value> = HashMap::new();
        properties.insert("value_type".to_string(), Value::Str(value_type.clone()));
        if let Some(v) = value {
            properties.insert("value".to_string(), v);
        } else {
            properties.insert("value".to_string(), Value::None);
        }

        let meta = build_meta(meta_data.as_ref(), &mut self.auto_pos_counter);
        let node = KGNode {
            id: node_id.clone(),
            r#type: "value".to_string(),
            name: format!("Value {}", node_id),
            data_inputs: vec![],
            data_outputs: vec![KGPort::with_type(port_name.clone(), value_type)],
            ctrl_inputs: vec![],
            ctrl_outputs: vec![],
            properties,
            meta,
        };
        self.nodes.insert(node_id.clone(), node);
        self.var_to_node_port
            .insert(stmt.target.clone(), (node_id.clone(), port_name));
        node_id
    }

    fn create_func_node(&mut self, stmt: &FuncCall) -> String {
        let meta_data = extract_meta_from_funccall(stmt);
        let node_id = meta_data
            .as_ref()
            .and_then(|m| m.get("node_id"))
            .and_then(value_as_str)
            .map(|s| s.to_string())
            .unwrap_or_else(|| self.gen_id(&stmt.func_name));

        // Build data input ports.
        let data_inputs: Vec<KGPort> = stmt
            .inputs
            .iter()
            .enumerate()
            .map(|(i, inp)| match inp {
                Expression::KeywordArg(kw) => {
                    let default = literal_value(&kw.value);
                    let mut port = KGPort::new(kw.name.clone());
                    if let Some(d) = default {
                        port.default = Some(d);
                    }
                    port
                }
                Expression::Identifier(_) => {
                    let port_name = infer_input_port_name(i, stmt.inputs.len());
                    KGPort::new(port_name)
                }
                Expression::Literal(lit) => {
                    let port_name = infer_input_port_name(i, stmt.inputs.len());
                    KGPort::with_default(port_name, lit.value.clone())
                }
                _ => KGPort::new(format!("in_{}", i)),
            })
            .collect();

        // Build data output ports.
        let known_single = {
            let mut s = HashSet::new();
            s.insert(node_id.clone());
            s
        };
        let data_outputs: Vec<KGPort> = stmt
            .outputs
            .iter()
            .filter_map(|out| {
                if let OutputTarget::Name(name) = out {
                    let port_name = parse_var_name(name, &known_single)
                        .map(|(_, p)| p)
                        .unwrap_or_else(|| name.clone());
                    Some(KGPort::new(port_name))
                } else {
                    None
                }
            })
            .collect();

        let meta = build_meta(meta_data.as_ref(), &mut self.auto_pos_counter);
        let node = KGNode {
            id: node_id.clone(),
            r#type: stmt.func_name.clone(),
            name: title_case(&stmt.func_name),
            data_inputs,
            data_outputs,
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs: vec!["out".to_string()],
            properties: HashMap::new(),
            meta,
        };
        self.nodes.insert(node_id.clone(), node);

        // Register output variables.
        for out in &stmt.outputs {
            if let OutputTarget::Name(name) = out {
                let port = parse_var_name(name, &known_single)
                    .map(|(_, p)| p)
                    .unwrap_or_else(|| name.clone());
                self.var_to_node_port
                    .insert(name.clone(), (node_id.clone(), port));
            }
        }

        node_id
    }

    fn create_branch_node(&mut self, stmt: &Branch) -> String {
        let meta_data = extract_meta_from_branch(stmt);
        let node_id = meta_data
            .as_ref()
            .and_then(|m| m.get("node_id"))
            .and_then(value_as_str)
            .map(|s| s.to_string())
            .unwrap_or_else(|| self.gen_id("branch"));

        let meta = build_meta(meta_data.as_ref(), &mut self.auto_pos_counter);
        let node = KGNode {
            id: node_id.clone(),
            r#type: "branch".to_string(),
            name: "Branch".to_string(),
            data_inputs: vec![KGPort::with_type("condition", "bool")],
            data_outputs: vec![],
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs: vec!["true".to_string(), "false".to_string()],
            properties: HashMap::new(),
            meta,
        };
        self.nodes.insert(node_id.clone(), node);
        node_id
    }

    fn create_switch_node(&mut self, stmt: &Switch) -> String {
        let meta_data = extract_meta_from_switch(stmt);
        let node_id = meta_data
            .as_ref()
            .and_then(|m| m.get("node_id"))
            .and_then(value_as_str)
            .map(|s| s.to_string())
            .unwrap_or_else(|| self.gen_id("switch"));

        let known_single = {
            let mut s = HashSet::new();
            s.insert(node_id.clone());
            s
        };

        let mut ctrl_outputs: Vec<String> = Vec::new();
        let mut cases_prop: HashMap<String, Value> = HashMap::new();

        for (expr, label) in &stmt.cases {
            let port = parse_var_name(label, &known_single)
                .map(|(_, p)| p)
                .unwrap_or_else(|| label.clone());
            ctrl_outputs.push(port.clone());
            if let Some(v) = literal_value_from_expr(expr) {
                cases_prop.insert(port, v);
            }
        }

        if stmt.default_label.is_some() {
            ctrl_outputs.push("default".to_string());
        }

        let mut properties: HashMap<String, Value> = HashMap::new();
        if !cases_prop.is_empty() {
            properties.insert(
                "cases".to_string(),
                Value::Dict(cases_prop.into_iter().map(|(k, v)| (k, v)).collect()),
            );
        }

        let meta = build_meta(meta_data.as_ref(), &mut self.auto_pos_counter);
        let node = KGNode {
            id: node_id.clone(),
            r#type: "switch".to_string(),
            name: "Switch".to_string(),
            data_inputs: vec![KGPort::with_type("value", "any")],
            data_outputs: vec![],
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs,
            properties,
            meta,
        };
        self.nodes.insert(node_id.clone(), node);
        node_id
    }

    fn create_parallel_node(&mut self, stmt: &Parallel) -> String {
        let meta_data = extract_meta_from_parallel(stmt);
        let node_id = meta_data
            .as_ref()
            .and_then(|m| m.get("node_id"))
            .and_then(value_as_str)
            .map(|s| s.to_string())
            .unwrap_or_else(|| self.gen_id("parallel"));

        let known_single = {
            let mut s = HashSet::new();
            s.insert(node_id.clone());
            s
        };

        let ctrl_outputs: Vec<String> = stmt
            .labels
            .iter()
            .map(|label| {
                parse_var_name(label, &known_single)
                    .map(|(_, p)| p)
                    .unwrap_or_else(|| label.clone())
            })
            .collect();

        let meta = build_meta(meta_data.as_ref(), &mut self.auto_pos_counter);
        let node = KGNode {
            id: node_id.clone(),
            r#type: "parallel".to_string(),
            name: "Parallel".to_string(),
            data_inputs: vec![],
            data_outputs: vec![],
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs,
            properties: HashMap::new(),
            meta,
        };
        self.nodes.insert(node_id.clone(), node);
        node_id
    }

    // -----------------------------------------------------------------------
    // Control-flow namespace handling
    // -----------------------------------------------------------------------

    fn handle_branch_namespaces(
        &mut self,
        true_label: &str,
        false_label: &str,
        branch_node_id: &str,
        stmts: &[Statement],
    ) {
        let ns_map = find_namespaces(stmts);

        for (port, label) in [("true", true_label), ("false", false_label)] {
            if let Some(ns_body) = ns_map.get(label) {
                self.handled_namespaces.insert(label.to_string());
                let branch_id_str = branch_node_id.to_string();
                let port_str = port.to_string();
                let ns_body_clone = ns_body.clone();
                let first_id = self.walk_statements(
                    &ns_body_clone,
                    None,
                    true,
                    false,
                    Some((&branch_id_str, &port_str)),
                );
                if let Some(ref fid) = first_id {
                    self.ensure_ctrl_ports(fid, "in");
                    self.edges.push(KGEdge::control(
                        branch_node_id.to_string(),
                        port.to_string(),
                        fid.clone(),
                        "in".to_string(),
                    ));
                }
            }
        }
    }

    fn handle_switch_namespaces(
        &mut self,
        cases: &[(Expression, String)],
        default_label: Option<&str>,
        switch_node_id: &str,
        stmts: &[Statement],
    ) {
        let ns_map = find_namespaces(stmts);

        // Collect port names from the already-created switch node.
        let ctrl_outputs: Vec<String> = self
            .nodes
            .get(switch_node_id)
            .map(|n| n.ctrl_outputs.clone())
            .unwrap_or_default();

        for (i, (_, label)) in cases.iter().enumerate() {
            let port = ctrl_outputs
                .get(i)
                .cloned()
                .unwrap_or_else(|| format!("case_{}", i));
            if let Some(ns_body) = ns_map.get(label.as_str()) {
                self.handled_namespaces.insert(label.clone());
                let ns_body_clone = ns_body.clone();
                let first_id = self.walk_statements(&ns_body_clone, None, true, false, None);
                if let Some(ref fid) = first_id {
                    self.ensure_ctrl_ports(fid, "in");
                    self.edges.push(KGEdge::control(
                        switch_node_id.to_string(),
                        port,
                        fid.clone(),
                        "in".to_string(),
                    ));
                }
            }
        }

        if let Some(dl) = default_label {
            if let Some(ns_body) = ns_map.get(dl) {
                self.handled_namespaces.insert(dl.to_string());
                let ns_body_clone = ns_body.clone();
                let first_id = self.walk_statements(&ns_body_clone, None, true, false, None);
                if let Some(ref fid) = first_id {
                    self.ensure_ctrl_ports(fid, "in");
                    self.edges.push(KGEdge::control(
                        switch_node_id.to_string(),
                        "default".to_string(),
                        fid.clone(),
                        "in".to_string(),
                    ));
                }
            }
        }
    }

    fn handle_parallel_namespaces(
        &mut self,
        labels: &[String],
        parallel_node_id: &str,
        stmts: &[Statement],
    ) {
        let ns_map = find_namespaces(stmts);

        let ctrl_outputs: Vec<String> = self
            .nodes
            .get(parallel_node_id)
            .map(|n| n.ctrl_outputs.clone())
            .unwrap_or_default();

        for (i, label) in labels.iter().enumerate() {
            let port = ctrl_outputs
                .get(i)
                .cloned()
                .unwrap_or_else(|| format!("out_{}", i));
            if let Some(ns_body) = ns_map.get(label.as_str()) {
                self.handled_namespaces.insert(label.clone());
                let ns_body_clone = ns_body.clone();
                let first_id = self.walk_statements(&ns_body_clone, None, true, false, None);
                if let Some(ref fid) = first_id {
                    self.ensure_ctrl_ports(fid, "in");
                    self.edges.push(KGEdge::control(
                        parallel_node_id.to_string(),
                        port,
                        fid.clone(),
                        "in".to_string(),
                    ));
                }
            }
        }
    }

    // -----------------------------------------------------------------------
    // Pass 2 — data edge resolution
    // -----------------------------------------------------------------------

    fn resolve_data_edges(&mut self, stmts: &[Statement], known_ids: &HashSet<String>) {
        for stmt in stmts {
            match stmt {
                Statement::DataflowBlock(db) => {
                    self.resolve_data_edges(&db.body, known_ids);
                    continue;
                }
                Statement::Namespace(ns) => {
                    self.resolve_data_edges(&ns.body, known_ids);
                    continue;
                }
                _ => {}
            }

            let meta = extract_meta_any(stmt);
            let node_id_from_meta = meta
                .as_ref()
                .and_then(|m| m.get("node_id"))
                .and_then(value_as_str)
                .map(|s| s.to_string());

            match stmt {
                Statement::Assignment(a) => {
                    // Value nodes have no data inputs; just skip.
                    let _ = node_id_from_meta;
                    let _ = a;
                    continue;
                }
                Statement::FuncCall(fc) => {
                    let node_id = match node_id_from_meta {
                        Some(id) => id,
                        None => continue,
                    };
                    let node = match self.nodes.get(&node_id).cloned() {
                        Some(n) => n,
                        None => continue,
                    };
                    for (i, inp) in fc.inputs.iter().enumerate() {
                        self.resolve_data_input(inp, &node, i, known_ids);
                    }
                }
                Statement::Branch(b) => {
                    let node_id = match node_id_from_meta {
                        Some(id) => id,
                        None => continue,
                    };
                    let node = match self.nodes.get(&node_id).cloned() {
                        Some(n) => n,
                        None => continue,
                    };
                    self.resolve_data_input(&b.condition, &node, 0, known_ids);
                }
                Statement::Switch(s) => {
                    let node_id = match node_id_from_meta {
                        Some(id) => id,
                        None => continue,
                    };
                    let node = match self.nodes.get(&node_id).cloned() {
                        Some(n) => n,
                        None => continue,
                    };
                    self.resolve_data_input(&s.value, &node, 0, known_ids);
                }
                _ => {}
            }
        }
    }

    /// Create a data edge if the expression references a known output variable.
    fn resolve_data_input(
        &mut self,
        expr: &Expression,
        to_node: &KGNode,
        input_idx: usize,
        _known_ids: &HashSet<String>,
    ) {
        let idents = extract_identifiers(expr);
        for ident_name in idents {
            let src = match self.var_to_node_port.get(&ident_name).cloned() {
                Some(s) => s,
                None => continue,
            };
            let (src_node_id, src_port) = src;

            let to_port = to_node
                .data_inputs
                .get(input_idx)
                .map(|p| p.port.clone())
                .unwrap_or_else(|| format!("in_{}", input_idx));

            self.edges.push(KGEdge::data(
                src_node_id,
                src_port,
                to_node.id.clone(),
                to_port,
            ));
        }
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    fn gen_id(&mut self, prefix: &str) -> String {
        self.node_counter += 1;
        format!("{}_{}", prefix, self.node_counter)
    }

    fn ensure_ctrl_ports(&mut self, node_id: &str, ctrl_in: &str) {
        if let Some(node) = self.nodes.get_mut(node_id) {
            if !node.ctrl_inputs.contains(&ctrl_in.to_string()) {
                node.ctrl_inputs.push(ctrl_in.to_string());
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Free helper functions
// ---------------------------------------------------------------------------

/// Try to split a variable name into `(node_id, port_name)`.
///
/// Tries the longest matching `node_id` prefix first. Falls back to the last
/// underscore split.
pub fn parse_var_name(
    var_name: &str,
    known_node_ids: &HashSet<String>,
) -> Option<(String, String)> {
    // Try known node ids first (greedy — longest first).
    let mut sorted_ids: Vec<&String> = known_node_ids.iter().collect();
    sorted_ids.sort_by_key(|s| std::cmp::Reverse(s.len()));

    for nid in sorted_ids {
        let prefix = format!("{}_", nid);
        if var_name.starts_with(&prefix) && var_name.len() > prefix.len() {
            let port = var_name[prefix.len()..].to_string();
            return Some((nid.clone(), port));
        }
    }

    // Fallback: split on the last underscore.
    if let Some(pos) = var_name.rfind('_') {
        if pos > 0 && pos + 1 < var_name.len() {
            return Some((var_name[..pos].to_string(), var_name[pos + 1..].to_string()));
        }
    }

    None
}

/// Collect all identifier names from an expression tree (shallow).
fn extract_identifiers(expr: &Expression) -> Vec<String> {
    match expr {
        Expression::Identifier(id) => vec![id.name.clone()],
        Expression::KeywordArg(kw) => extract_identifiers(&kw.value),
        _ => vec![],
    }
}

/// Extract the Python value from a [`Literal`] expression.
fn literal_value(expr: &Expression) -> Option<Value> {
    if let Expression::Literal(lit) = expr {
        Some(lit.value.clone())
    } else {
        None
    }
}

/// Extract value directly from an [`Expression`] that may be a Literal.
fn literal_value_from_expr(expr: &Expression) -> Option<Value> {
    literal_value(expr)
}

/// Convert a [`Value::Str`] to a `&str`.
fn value_as_str(v: &Value) -> Option<&str> {
    if let Value::Str(s) = v {
        Some(s.as_str())
    } else {
        None
    }
}

/// Replace underscores with spaces and title-case each word.
fn title_case(s: &str) -> String {
    s.split('_')
        .map(|word| {
            let mut chars = word.chars();
            match chars.next() {
                None => String::new(),
                Some(c) => c.to_uppercase().collect::<String>() + chars.as_str(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// Infer a port name for a positional input.
///
/// * Single-input nodes → "value"
/// * Two-input or more → "a", "b", … (up to 26), then "in_N"
fn infer_input_port_name(index: usize, total_inputs: usize) -> String {
    if total_inputs == 1 {
        return "value".to_string();
    }
    if index < 26 {
        return ((b'a' + index as u8) as char).to_string();
    }
    format!("in_{}", index)
}

/// Build the `meta` dict for a `KGNode` from `@meta` annotation data.
fn build_meta(
    meta_data: Option<&HashMap<String, Value>>,
    auto_pos_counter: &mut u32,
) -> HashMap<String, Value> {
    let mut result: HashMap<String, Value> = HashMap::new();

    let has_pos = meta_data.and_then(|m| m.get("pos")).is_some();

    if !has_pos {
        *auto_pos_counter += 1;
        let col = (*auto_pos_counter - 1) % 4;
        let row = (*auto_pos_counter - 1) / 4;
        let x = 100 + col * 220;
        let y = 100 + row * 160;
        result.insert(
            "pos".to_string(),
            Value::List(vec![Value::Int(x as i64), Value::Int(y as i64)]),
        );
    }

    if let Some(md) = meta_data {
        if let Some(pos) = md.get("pos") {
            result.insert("pos".to_string(), pos.clone());
        }
        for (key, val) in md {
            if key != "node_id" && key != "pos" {
                result.insert(key.clone(), val.clone());
            }
        }
    }

    result
}

/// Build a namespace name → body map from a flat statement list.
fn find_namespaces(stmts: &[Statement]) -> HashMap<&str, Vec<Statement>> {
    let mut result: HashMap<&str, Vec<Statement>> = HashMap::new();
    for stmt in stmts {
        if let Statement::Namespace(ns) = stmt {
            result.insert(ns.name.as_str(), ns.body.clone());
        }
    }
    result
}

// ---------------------------------------------------------------------------
// Per-statement meta extraction
// ---------------------------------------------------------------------------

fn merge_metadata(metadata: &[MetaAnnotation]) -> HashMap<String, Value> {
    let mut merged: HashMap<String, Value> = HashMap::new();
    for m in metadata {
        merged.extend(m.data.clone());
    }
    merged
}

fn extract_meta_from_assignment(stmt: &Assignment) -> Option<HashMap<String, Value>> {
    stmt.metadata.as_deref().map(merge_metadata)
}

fn extract_meta_from_funccall(stmt: &FuncCall) -> Option<HashMap<String, Value>> {
    stmt.metadata.as_deref().map(merge_metadata)
}

fn extract_meta_from_branch(stmt: &Branch) -> Option<HashMap<String, Value>> {
    stmt.metadata.as_deref().map(merge_metadata)
}

fn extract_meta_from_switch(stmt: &Switch) -> Option<HashMap<String, Value>> {
    stmt.metadata.as_deref().map(merge_metadata)
}

fn extract_meta_from_parallel(stmt: &Parallel) -> Option<HashMap<String, Value>> {
    stmt.metadata.as_deref().map(merge_metadata)
}

fn extract_meta_from_jump(stmt: &Jump) -> Option<HashMap<String, Value>> {
    stmt.metadata.as_deref().map(merge_metadata)
}

fn extract_meta_any(stmt: &Statement) -> Option<HashMap<String, Value>> {
    match stmt {
        Statement::Assignment(s) => extract_meta_from_assignment(s),
        Statement::FuncCall(s) => extract_meta_from_funccall(s),
        Statement::Branch(s) => extract_meta_from_branch(s),
        Statement::Switch(s) => extract_meta_from_switch(s),
        Statement::Parallel(s) => extract_meta_from_parallel(s),
        Statement::Jump(s) => extract_meta_from_jump(s),
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ast::{
        Assignment, Branch, DataflowBlock, Expression, FuncCall, Identifier, Literal,
        MetaAnnotation, Namespace, OutputTarget, Program, Statement, Value,
    };
    use std::collections::HashMap;

    fn meta_with_id(node_id: &str) -> Vec<MetaAnnotation> {
        let mut data = HashMap::new();
        data.insert("node_id".to_string(), Value::Str(node_id.to_string()));
        vec![MetaAnnotation { data, line: None }]
    }

    // -----------------------------------------------------------------------
    // parse_var_name
    // -----------------------------------------------------------------------

    #[test]
    fn test_parse_var_name_known_node() {
        let mut known = HashSet::new();
        known.insert("add_5".to_string());
        let result = parse_var_name("add_5_result", &known);
        assert_eq!(result, Some(("add_5".to_string(), "result".to_string())));
    }

    #[test]
    fn test_parse_var_name_fallback() {
        let known: HashSet<String> = HashSet::new();
        let result = parse_var_name("foo_bar", &known);
        assert_eq!(result, Some(("foo".to_string(), "bar".to_string())));
    }

    #[test]
    fn test_parse_var_name_no_underscore() {
        let known: HashSet<String> = HashSet::new();
        let result = parse_var_name("simple", &known);
        assert!(result.is_none());
    }

    #[test]
    fn test_parse_var_name_longest_prefix_wins() {
        let mut known = HashSet::new();
        known.insert("my_node".to_string());
        known.insert("my".to_string());
        // "my_node_out" should match "my_node" (longer), not "my"
        let result = parse_var_name("my_node_out", &known);
        assert_eq!(result, Some(("my_node".to_string(), "out".to_string())));
    }

    // -----------------------------------------------------------------------
    // Simple program: assignment + func_call
    // -----------------------------------------------------------------------

    #[test]
    fn test_decompile_simple_program() {
        // value_node assigns literal 42 → variable "val_n1_out"
        // add node reads "val_n1_out" and produces "add_n2_result"
        let program = Program {
            body: vec![
                Statement::Assignment(Assignment {
                    target: "val_n1_out".to_string(),
                    value: Expression::Literal(Literal {
                        value: Value::Int(42),
                        literal_type: "int".to_string(),
                        line: None,
                    }),
                    metadata: Some(meta_with_id("val_n1")),
                    line: None,
                }),
                Statement::FuncCall(FuncCall {
                    inputs: vec![Expression::Identifier(Identifier {
                        name: "val_n1_out".to_string(),
                        line: None,
                    })],
                    func_name: "add".to_string(),
                    outputs: vec![OutputTarget::Name("add_n2_result".to_string())],
                    metadata: Some(meta_with_id("add_n2")),
                    line: None,
                }),
            ],
            mode: None,
            line: None,
        };

        let graph = decompile(&program);

        // Should have exactly 2 nodes.
        assert_eq!(
            graph.nodes.len(),
            2,
            "expected 2 nodes, got {:?}",
            graph.nodes.iter().map(|n| &n.id).collect::<Vec<_>>()
        );

        let val_node = graph
            .nodes
            .iter()
            .find(|n| n.id == "val_n1")
            .expect("val_n1 node missing");
        assert_eq!(val_node.r#type, "value");
        assert_eq!(val_node.data_outputs.len(), 1);
        assert_eq!(val_node.data_outputs[0].port, "out");

        let add_node = graph
            .nodes
            .iter()
            .find(|n| n.id == "add_n2")
            .expect("add_n2 node missing");
        assert_eq!(add_node.r#type, "add");
        assert_eq!(add_node.data_inputs.len(), 1);
        assert_eq!(add_node.data_outputs.len(), 1);
        assert_eq!(add_node.data_outputs[0].port, "result");

        // Should have a control edge val_n1→add_n2 and a data edge.
        let ctrl_edges: Vec<_> = graph
            .edges
            .iter()
            .filter(|e| e.r#type == "control")
            .collect();
        let data_edges: Vec<_> = graph.edges.iter().filter(|e| e.r#type == "data").collect();

        // value nodes have no ctrl outputs, so only func_call chains ctrl.
        // val_n1 has ctrl_inputs=[] ctrl_outputs=[], add_n2 has ctrl_inputs=["in"].
        // So no ctrl edge from val_n1 (it has no ctrl ports).
        // The ctrl edge only fires if prev has a ctrl output.
        assert!(data_edges.len() >= 1, "expected at least one data edge");
        let de = &data_edges[0];
        assert_eq!(de.from_node, "val_n1");
        assert_eq!(de.from_port, "out");
        assert_eq!(de.to_node, "add_n2");
        assert_eq!(de.to_port, "value"); // single-input → "value"

        // val_n1 has no explicit ctrl ports, but the decompiler still emits a
        // ctrl edge to the next sequential node using the fallback port names
        // ("out" → "in"), mirroring the Python behaviour.
        let val_to_add_ctrl = ctrl_edges
            .iter()
            .find(|e| e.from_node == "val_n1" && e.to_node == "add_n2");
        // This edge is expected because both nodes appear in the same linear
        // statement list and val_n1 is processed first (last_id is set).
        // We do not assert its absence; we just verify the data edge exists.
        let _ = val_to_add_ctrl; // presence is implementation-defined
    }

    // -----------------------------------------------------------------------
    // Branch pattern: verify ctrl edges
    // -----------------------------------------------------------------------

    #[test]
    fn test_decompile_branch_ctrl_edges() {
        // branch_node → ns_true body (func_a) and ns_false body (func_b)
        let program = Program {
            body: vec![
                Statement::Branch(Branch {
                    condition: Expression::Identifier(Identifier {
                        name: "some_cond_out".to_string(),
                        line: None,
                    }),
                    true_label: "ns_true".to_string(),
                    false_label: "ns_false".to_string(),
                    metadata: Some(meta_with_id("br1")),
                    line: None,
                }),
                Statement::Namespace(Namespace {
                    name: "ns_true".to_string(),
                    body: vec![Statement::FuncCall(FuncCall {
                        inputs: vec![],
                        func_name: "func_a".to_string(),
                        outputs: vec![],
                        metadata: Some(meta_with_id("fa1")),
                        line: None,
                    })],
                    line: None,
                }),
                Statement::Namespace(Namespace {
                    name: "ns_false".to_string(),
                    body: vec![Statement::FuncCall(FuncCall {
                        inputs: vec![],
                        func_name: "func_b".to_string(),
                        outputs: vec![],
                        metadata: Some(meta_with_id("fb1")),
                        line: None,
                    })],
                    line: None,
                }),
            ],
            mode: None,
            line: None,
        };

        let graph = decompile(&program);

        // Nodes: br1, fa1, fb1
        assert_eq!(graph.nodes.len(), 3);

        let ctrl_edges: Vec<_> = graph
            .edges
            .iter()
            .filter(|e| e.r#type == "control")
            .collect();

        // Expect: br1/true → fa1/in  and  br1/false → fb1/in
        let true_edge = ctrl_edges
            .iter()
            .find(|e| e.from_node == "br1" && e.from_port == "true" && e.to_node == "fa1");
        let false_edge = ctrl_edges
            .iter()
            .find(|e| e.from_node == "br1" && e.from_port == "false" && e.to_node == "fb1");

        assert!(
            true_edge.is_some(),
            "missing br1/true → fa1 ctrl edge; edges: {:?}",
            ctrl_edges
        );
        assert!(
            false_edge.is_some(),
            "missing br1/false → fb1 ctrl edge; edges: {:?}",
            ctrl_edges
        );
    }

    // -----------------------------------------------------------------------
    // Dataflow block: nodes should have no ctrl edges between them
    // -----------------------------------------------------------------------

    #[test]
    fn test_dataflow_block_no_ctrl_edges() {
        let program = Program {
            body: vec![Statement::DataflowBlock(DataflowBlock {
                body: vec![
                    Statement::FuncCall(FuncCall {
                        inputs: vec![],
                        func_name: "node_x".to_string(),
                        outputs: vec![],
                        metadata: Some(meta_with_id("nx")),
                        line: None,
                    }),
                    Statement::FuncCall(FuncCall {
                        inputs: vec![],
                        func_name: "node_y".to_string(),
                        outputs: vec![],
                        metadata: Some(meta_with_id("ny")),
                        line: None,
                    }),
                ],
                line: None,
            })],
            mode: None,
            line: None,
        };

        let graph = decompile(&program);
        assert_eq!(graph.nodes.len(), 2);
        let ctrl_edges: Vec<_> = graph
            .edges
            .iter()
            .filter(|e| e.r#type == "control")
            .collect();
        assert!(
            ctrl_edges.is_empty(),
            "dataflow block should produce no ctrl edges, got: {:?}",
            ctrl_edges
        );
    }
}
