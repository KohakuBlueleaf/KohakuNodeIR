//! Text -> graph view: a program as node graphs (graph.md).

use std::collections::{HashMap, HashSet};

use crate::errors::{KirError, Result};
use crate::flow::cfg::{build_cfg, reaching, reaching_with, Cfg, NodeKind, Reaching, UNDEF};
use crate::origins::origin_json;
use crate::sig::env::NodeEnv;
use crate::sig::types::type_text;
use crate::syntax::ast::{Arg, Expr, Kind, OutParam, Param, Program, Stmt, Uid};
use crate::syntax::value::Value;
use crate::syntax::writer::write_type;
use crate::util::json::Json;
use crate::util::pyfmt::{str_list_repr, str_repr};

pub const FORMAT: i64 = 3;

/// (node id, port name)
type PortRef = (String, String);

fn port_ref(node: &str, port: &str) -> PortRef {
    (node.to_string(), port.to_string())
}

/// One entry of a node's `inputs` / `outputs`.
#[derive(Clone, Debug, Default)]
struct PortEntry {
    port: String,
    keyword: bool,
    /// Absent, or the bound name (`None` is a discarded `_`).
    var: Option<Option<String>>,
    ty: Option<String>,
    value: Option<Json>,
    deferred: Option<&'static str>,
}

impl PortEntry {
    fn named(port: &str) -> PortEntry {
        PortEntry { port: port.to_string(), ..PortEntry::default() }
    }

    fn to_json(&self) -> Json {
        let mut o = vec![("port".to_string(), Json::str(&self.port))];
        if self.keyword {
            o.push(("keyword".into(), Json::Bool(true)));
        }
        if let Some(var) = &self.var {
            o.push(("var".into(), Json::opt_str(var.as_deref())));
        }
        if let Some(t) = &self.ty {
            o.push(("type".into(), Json::str(t)));
        }
        if let Some(deferred) = self.deferred {
            o.push(("deferred".into(), Json::str(deferred)));
        }
        if let Some(v) = &self.value {
            o.push(("value".into(), v.clone()));
        }
        Json::Object(o)
    }
}

#[derive(Debug, Default)]
struct GNode {
    id: String,
    kind: &'static str,
    name: Option<String>,
    props: Option<Json>,
    inputs: Option<Vec<PortEntry>>,
    outputs: Option<Vec<PortEntry>>,
    ctrl_in: Option<Vec<String>>,
    ctrl_out: Option<Vec<String>>,
    meta: Option<Json>,
    hints: Option<Json>,
    origin: Option<Json>,
    path: Option<String>,
    region: Option<String>,
    namespace_origins: Option<Json>,
    entry: bool,
}

impl GNode {
    fn new(kind: &'static str) -> GNode {
        GNode { kind, ..GNode::default() }
    }

    fn props(mut self, pairs: Vec<(&str, Json)>) -> GNode {
        self.props = Some(Json::Object(pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect()));
        self
    }

    fn ctrl(mut self, ins: &[&str], outs: &[&str]) -> GNode {
        self.ctrl_in = Some(ins.iter().map(|s| s.to_string()).collect());
        self.ctrl_out = Some(outs.iter().map(|s| s.to_string()).collect());
        self
    }

    fn to_json(&self) -> Json {
        let ports = |list: &Vec<PortEntry>| Json::Array(list.iter().map(PortEntry::to_json).collect());
        let mut o = vec![("id".to_string(), Json::str(&self.id)), ("kind".to_string(), Json::str(self.kind))];
        let mut put = |k: &str, v: Option<Json>| {
            if let Some(v) = v {
                o.push((k.to_string(), v));
            }
        };
        put("name", self.name.as_deref().map(Json::str));
        put("props", self.props.clone());
        put("inputs", self.inputs.as_ref().map(ports));
        put("outputs", self.outputs.as_ref().map(ports));
        put("ctrl_in", self.ctrl_in.as_ref().map(|c| Json::strs(c)));
        put("ctrl_out", self.ctrl_out.as_ref().map(|c| Json::strs(c)));
        put("meta", self.meta.clone());
        put("hints", self.hints.clone());
        put("origin", self.origin.clone());
        put("path", self.path.as_deref().map(Json::str));
        put("region", self.region.as_deref().map(Json::str));
        put("namespace_origins", self.namespace_origins.clone());
        if self.entry {
            put("entry", Some(Json::Bool(true)));
        }
        Json::Object(o)
    }
}

struct Edge {
    kind: &'static str,
    from: PortRef,
    to: PortRef,
    origin: Option<Json>,
}

impl Edge {
    fn to_json(&self) -> Json {
        let end = |p: &PortRef| Json::Object(vec![("node".into(), Json::str(&p.0)), ("port".into(), Json::str(&p.1))]);
        let mut out = Json::Object(vec![
            ("kind".into(), Json::str(self.kind)),
            ("from".into(), end(&self.from)),
            ("to".into(), end(&self.to)),
        ]);
        if let Some(origin) = &self.origin {
            out.insert("origin", origin.clone());
        }
        out
    }
}

/// A literal as graph JSON: tuples and dicts in their tagged forms.
pub fn json_literal(v: &Value) -> Json {
    match v {
        Value::Tuple(items) => {
            Json::Object(vec![("tuple".into(), Json::Array(items.iter().map(json_literal).collect()))])
        }
        Value::List(items) => Json::Array(items.iter().map(json_literal).collect()),
        Value::Dict(pairs) if pairs.iter().all(|(k, _)| matches!(k, Value::Str(_))) => {
            let obj = pairs
                .iter()
                .map(|(k, x)| match k {
                    Value::Str(s) => (s.clone(), json_literal(x)),
                    _ => unreachable!("string keys"),
                })
                .collect();
            Json::Object(vec![("dict".into(), Json::Object(obj))])
        }
        Value::Dict(pairs) => Json::Object(vec![(
            "pairs".into(),
            Json::Array(pairs.iter().map(|(k, x)| Json::Array(vec![json_literal(k), json_literal(x)])).collect()),
        )]),
        Value::None => Json::Null,
        Value::Bool(b) => Json::Bool(*b),
        Value::Int(n) => Json::Int(n.clone()),
        Value::Float(f) => Json::Float(*f),
        Value::Str(s) => Json::Str(s.clone()),
    }
}

fn value_json(v: &Value) -> Result<Json> {
    v.to_json().map_err(KirError::Value)
}

/// `uid -> (path, structural path)`: the path is the statement's origin id (`meta.node_id`,
/// else the structural path), as `stamp_origins` assigns it.
fn stmt_paths(body: &[Stmt], prefix: &str, out: &mut HashMap<Uid, (String, String)>) {
    for (index, stmt) in body.iter().enumerate() {
        let node_path = format!("{prefix}/{index}");
        let path = stmt
            .meta
            .get("node_id")
            .filter(|v| !matches!(v, Value::None))
            .map_or_else(|| node_path.clone(), |v| v.py_str());
        out.insert(stmt.uid, (path, node_path.clone()));
        for (child_index, block) in stmt.children().into_iter().enumerate() {
            let field = if child_index == 0 { "body" } else { "handler" };
            stmt_paths(block, &format!("{node_path}/{field}"), out);
        }
    }
}

/// One region of a graph: a namespace, try or handler body, or dataflow block.
struct Region {
    id: String,
    kind: &'static str,
    parent: Option<String>,
    owner: Option<(String, Option<String>)>,
    label: Option<String>,
}

impl Region {
    fn to_json(&self) -> Json {
        let mut o = vec![("id".to_string(), Json::str(&self.id)), ("kind".to_string(), Json::str(self.kind))];
        if let Some(parent) = &self.parent {
            o.push(("parent".into(), Json::str(parent)));
        }
        if let Some((node, port)) = &self.owner {
            let owner =
                vec![("node".to_string(), Json::str(node)), ("port".to_string(), Json::opt_str(port.as_deref()))];
            o.push(("owner".into(), Json::Object(owner)));
        }
        if let Some(label) = &self.label {
            o.push(("label".into(), Json::str(label)));
        }
        Json::Object(o)
    }
}

/// Builds one graph: the top level or one `@def`.
struct Scope<'a> {
    env: Option<&'a NodeEnv>,
    name: String,
    body: &'a [Stmt],
    params: &'a [Param],
    outputs: &'a [OutParam],
    paths: HashMap<Uid, (String, String)>,
    regions: Vec<Region>,
    region: Option<String>,
    nodes: Vec<GNode>,
    index: HashMap<String, usize>,
    edges: Vec<Edge>,
    count: usize,
    ids: HashSet<String>,
    stmt_node: HashMap<Uid, String>,
    merges: HashMap<String, String>,
    pending: HashMap<Uid, Vec<PortRef>>,
    emitted: HashSet<Uid>,
    stack: Vec<&'a [Stmt]>,
    cfg: Cfg<'a>,
    inn: Reaching,
    /// With variables: what reaches each node on the way in (no loop closing edges).
    inn_forward: Option<Reaching>,
    /// Names with a read reached by several writes.
    multi: HashSet<String>,
    bind_owner: HashMap<usize, Uid>,
    /// The `variables` data style: a value inside the graph goes through its variable.
    variables: bool,
    /// With variables, reads `(cfg node, name, target, region)` and writes `(source, name,
    /// region)` wait until every write has its node (`resolve_variables`).
    var_reads: Vec<(usize, String, PortRef, Option<String>)>,
    var_writes: Vec<(PortRef, String, Option<String>)>,
}

impl<'a> Scope<'a> {
    fn new(
        env: Option<&'a NodeEnv>,
        name: &str,
        body: &'a [Stmt],
        params: &'a [Param],
        outputs: &'a [OutParam],
        data: DataStyle,
        prefix: &str,
    ) -> Self {
        let mut paths = HashMap::new();
        stmt_paths(body, prefix, &mut paths);
        let param_names: Vec<String> = params.iter().map(|p| p.name.clone()).collect();
        let cfg = build_cfg(body, &param_names);
        let inn = reaching(&cfg, &[]);
        let several = |n: usize, x: &str| {
            let mut ds = inn.defs_of(n, x);
            ds.remove(&UNDEF);
            ds.len() > 1
        };
        let mut multi = HashSet::new();
        for n in cfg.reachable() {
            for x in &cfg.nodes[n].reads {
                if several(n, x) {
                    multi.insert(x.clone());
                }
            }
        }
        for o in outputs {
            if several(cfg.exit, &o.name) {
                multi.insert(o.name.clone());
            }
        }
        let bind_owner = cfg.binds.iter().map(|(&owner, &bind)| (bind, owner)).collect();
        let variables = data == DataStyle::Variables;
        let inn_forward = variables.then(|| reaching_with(&cfg, &[], true));
        Scope {
            env,
            name: name.to_string(),
            body,
            params,
            outputs,
            paths,
            regions: Vec::new(),
            region: None,
            nodes: Vec::new(),
            index: HashMap::new(),
            edges: Vec::new(),
            count: 0,
            ids: HashSet::new(),
            stmt_node: HashMap::new(),
            merges: HashMap::new(),
            pending: HashMap::new(),
            emitted: HashSet::new(),
            stack: Vec::new(),
            cfg,
            inn,
            inn_forward,
            multi,
            bind_owner,
            variables,
            var_reads: Vec::new(),
            var_writes: Vec::new(),
        }
    }

    // ------------------------------------------------------------ nodes and edges
    fn new_id(&mut self, base: &str, stmt: Option<&Stmt>) -> String {
        self.count += 1;
        let mut nid = match stmt.and_then(|s| s.meta.get("node_id")) {
            Some(v) => v.py_str(),
            None => format!("{}_{}", base.replace('.', "_"), self.count),
        };
        while self.ids.contains(&nid) {
            nid.push('_');
        }
        self.ids.insert(nid.clone());
        nid
    }

    fn push(&mut self, n: GNode) -> usize {
        self.index.entry(n.id.clone()).or_insert(self.nodes.len());
        self.nodes.push(n);
        self.nodes.len() - 1
    }

    fn node(&mut self, mut n: GNode, base: &str, stmt: Option<&Stmt>) -> Result<usize> {
        n.id = self.new_id(base, stmt);
        if let Some(s) = stmt {
            n.origin = s.origin.as_ref().map(origin_json);
            let meta: Vec<(String, Json)> = s
                .meta
                .iter()
                .filter(|(k, _)| k.as_str() != "node_id")
                .map(|(k, v)| Ok((k.clone(), value_json(v)?)))
                .collect::<Result<_>>()?;
            if !meta.is_empty() {
                n.meta = Some(Json::Object(meta));
            }
            if !s.hint.is_empty() {
                let hints = s.hint.iter().map(|(k, v)| Ok((k.clone(), value_json(v)?))).collect::<Result<_>>()?;
                n.hints = Some(Json::Object(hints));
            }
            n.path = Some(self.paths[&s.uid].0.clone());
            self.stmt_node.insert(s.uid, n.id.clone());
        }
        n.region = self.region.clone();
        Ok(self.push(n))
    }

    /// Enter region `id`; the region it was opened in is returned for closing.
    fn open_region(
        &mut self,
        id: String,
        kind: &'static str,
        owner: Option<(String, Option<String>)>,
        label: Option<String>,
    ) -> Option<String> {
        self.regions.push(Region { id: id.clone(), kind, parent: self.region.clone(), owner, label });
        self.region.replace(id)
    }

    fn id(&self, n: usize) -> String {
        self.nodes[n].id.clone()
    }

    fn by_id(&self, id: &str) -> Option<&GNode> {
        self.index.get(id).map(|&i| &self.nodes[i])
    }

    fn ctrl(&mut self, from: PortRef, to: PortRef) {
        self.edges.push(Edge { kind: "ctrl", from, to, origin: None });
    }

    fn data(&mut self, from: PortRef, to: PortRef) {
        self.edges.push(Edge { kind: "data", from, to, origin: None });
    }

    /// Connect incoming control to `target`, through a merge node when several.
    fn join(&mut self, mut incoming: Vec<PortRef>, target: PortRef) -> Result<()> {
        if incoming.len() > 1 {
            let ins: Vec<String> = (0..incoming.len()).map(|i| format!("in_{i}")).collect();
            let mut g = GNode::new("merge");
            g.ctrl_in = Some(ins.clone());
            g.ctrl_out = Some(vec!["out".into()]);
            let m = self.node(g, "merge", None)?;
            let mid = self.id(m);
            for (p, port) in incoming.into_iter().zip(ins) {
                self.ctrl(p, (mid.clone(), port));
            }
            incoming = vec![port_ref(&mid, "out")];
        }
        for p in incoming {
            self.ctrl(p, target.clone());
        }
        Ok(())
    }

    // ------------------------------------------------------------ data
    fn writer_port(&self, def_node: i64, name: &str) -> Option<PortRef> {
        let def_node = def_node as usize;
        if def_node == self.cfg.entry {
            return Some(port_ref("inputs", name));
        }
        let node = &self.cfg.nodes[def_node];
        if node.kind == NodeKind::Bind {
            let owner = self.bind_owner.get(&def_node)?;
            let nid = self.stmt_node.get(owner)?;
            let n = self.by_id(nid)?;
            if n.kind == "try" {
                return Some(port_ref(nid, "error"));
            }
            let item = n.props.as_ref().and_then(|p| p.get("item")).and_then(Json::as_str);
            return Some(port_ref(nid, if item == Some(name) { "item" } else { "index" }));
        }
        let s = node.stmt?;
        let nid = self.stmt_node.get(&s.uid)?;
        if matches!(s.kind, Kind::Assign { .. }) {
            return Some(port_ref(nid, "value"));
        }
        let n = self.by_id(nid)?;
        let outputs = n.outputs.as_ref()?;
        // Output ports follow the statement's outputs in order (a port names its variable only in wires)
        if let Kind::Call { outs, .. } = &s.kind {
            if let Some((_, p)) = outs.iter().zip(outputs).find(|(o, _)| o.as_deref() == Some(name)) {
                return Some(port_ref(nid, &p.port));
            }
        }
        outputs.iter().find(|p| matches!(&p.var, Some(Some(v)) if v == name)).map(|p| port_ref(nid, &p.port))
    }

    fn get_node(&mut self, name: &str) -> Result<String> {
        let g = GNode::new("get").props(vec![("name", Json::str(name))]);
        let g = GNode { outputs: Some(vec![PortEntry::named("value")]), ..g };
        let n = self.node(g, "get", None)?;
        Ok(self.id(n))
    }

    /// A read: a direct wire from its only write, or a `get` variable node. With
    /// variables it waits until every write has its node (`resolve_variables`).
    fn wire_read(&mut self, cfg_node: usize, name: &str, target: PortRef) -> Result<()> {
        if self.variables {
            self.var_reads.push((cfg_node, name.to_string(), target, self.region.clone()));
            return Ok(());
        }
        if !self.multi.contains(name) {
            let mut defs = self.inn.defs_of(cfg_node, name);
            defs.remove(&UNDEF);
            if defs.len() == 1 {
                if let Some(src) = self.writer_port(*defs.iter().next().expect("one def"), name) {
                    self.data(src, target);
                    return Ok(());
                }
            }
        }
        let g = self.get_node(name)?;
        self.data(port_ref(&g, "value"), target);
        Ok(())
    }

    /// An output port; with variables, a written name is shown by its `set` node instead.
    fn out_entry(&self, port: &str, name: Option<&str>, ty: Option<String>) -> PortEntry {
        let var = match name {
            None => Some(None),
            Some(n) if !self.variables => Some(Some(n.to_string())),
            Some(_) => None,
        };
        PortEntry { var, ty, ..PortEntry::named(port) }
    }

    /// A write: a `set` variable node on the output port (with variables, or for a
    /// name written on several paths).
    fn bind_out(&mut self, src: PortRef, name: Option<&str>) -> Result<()> {
        let Some(name) = name.filter(|n| self.variables || self.multi.contains(*n)) else { return Ok(()) };
        if self.variables {
            // The graph's inputs reach their readers directly (`resolve_variables`)
            if src.0 != "inputs" {
                self.var_writes.push((src, name.to_string(), self.region.clone()));
            }
            return Ok(());
        }
        self.set_node(src, name)
    }

    fn set_node(&mut self, src: PortRef, name: &str) -> Result<()> {
        let g = GNode::new("set").props(vec![("name", Json::str(name))]);
        let st = self.node(GNode { inputs: Some(vec![PortEntry::named("value")]), ..g }, "set", None)?;
        let sid = self.id(st);
        self.data(src, port_ref(&sid, "value"));
        Ok(())
    }

    /// The variables style's reads and writes, once every write has its node.
    ///
    /// Inside the graph a value goes through its variable: a `get` reads it, a `set` is
    /// drawn for every write of a name some `get` reads. The graph's own inputs and
    /// outputs are never wired to a variable. A read only the input reaches on the way
    /// in (forward reaching: inside a loop, what entered it) is wired from the input; a
    /// graph output only one write decides (the input left out when the program writes
    /// the name) is wired from that write. Otherwise an assign statement (`join`) stands
    /// where the value is decided: for an output, right before the end, reading the
    /// variable; for an input other writes meet, right after the start, writing it.
    fn resolve_variables(&mut self) -> Result<()> {
        let entry = self.cfg.entry as i64;
        let mut read_names: HashSet<String> = HashSet::new();
        let mut init_names: Vec<String> = Vec::new();
        for (cfg_node, name, target, region) in std::mem::take(&mut self.var_reads) {
            let at_exit = cfg_node == self.cfg.exit;
            let reach = if at_exit { &self.inn } else { self.inn_forward.as_ref().expect("variables") };
            let mut defs: Vec<i64> = reach.defs_of(cfg_node, &name).into_iter().filter(|&d| d != UNDEF).collect();
            if at_exit && defs.iter().any(|&d| d != entry) {
                defs.retain(|&d| d != entry);
            }
            let srcs: Vec<Option<PortRef>> = defs.iter().map(|&d| self.writer_port(d, &name)).collect();
            if defs.len() == 1 && srcs[0].is_some() && (at_exit || defs[0] == entry) {
                self.data(srcs[0].clone().expect("a source"), target);
                continue;
            }
            if defs.contains(&entry) && !init_names.contains(&name) {
                init_names.push(name.clone());
            }
            let mut target = target;
            if at_exit && !defs.is_empty() {
                let j = self.assign_on_flow(&name, &target.0, true)?;
                self.data(port_ref(&j, "value"), target);
                target = port_ref(&j, "value");
            }
            let outer = std::mem::replace(&mut self.region, if at_exit { None } else { region });
            let g = self.get_node(&name)?;
            self.data(port_ref(&g, "value"), target);
            self.region = outer;
            read_names.insert(name);
        }
        for name in init_names {
            let j = self.assign_on_flow(&name, "inputs", false)?;
            self.data(port_ref("inputs", &name), port_ref(&j, "value"));
            self.var_writes.push((port_ref(&j, "value"), name, None));
        }
        for (src, name, region) in std::mem::take(&mut self.var_writes) {
            if read_names.contains(&name) {
                let outer = std::mem::replace(&mut self.region, region);
                self.set_node(src, &name)?;
                self.region = outer;
                continue;
            }
            // A write nothing reads keeps its name on its own port
            let n = self.index[&src.0];
            for p in self.nodes[n].outputs.iter_mut().flatten().filter(|p| p.port == src.1) {
                p.var = Some(Some(name.clone()));
            }
        }
        Ok(())
    }

    /// An assign statement (`join`, one input) of `name` spliced into the control flow
    /// right before node `at` (into its `in`) or right after it (out of its `out`).
    fn assign_on_flow(&mut self, name: &str, at: &str, before: bool) -> Result<String> {
        let g = GNode::new("join").props(vec![("name", Json::str(name))]).ctrl(&["in"], &["out"]);
        let g = GNode {
            inputs: Some(vec![PortEntry::named("value")]),
            outputs: Some(vec![PortEntry::named("value")]),
            ..g
        };
        let n = self.node(g, "join", None)?;
        let j = self.id(n);
        let end = port_ref(at, if before { "in" } else { "out" });
        for e in self.edges.iter_mut().filter(|e| e.kind == "ctrl") {
            let side = if before { &mut e.to } else { &mut e.from };
            if *side == end {
                *side = port_ref(&j, if before { "in" } else { "out" });
            }
        }
        if before {
            self.ctrl(port_ref(&j, "out"), port_ref(at, "in"));
        } else {
            self.ctrl(port_ref(at, "out"), port_ref(&j, "in"));
        }
        Ok(j)
    }

    fn bind_outs(&mut self, s: &Stmt, n: usize) -> Result<()> {
        let names: Vec<Option<String>> = match &s.kind {
            Kind::Assign { target, .. } => vec![Some(target.clone())],
            Kind::Call { outs, .. } => outs.clone(),
            _ => vec![],
        };
        let id = self.id(n);
        let ports: Vec<String> =
            self.nodes[n].outputs.as_ref().map_or(vec![], |o| o.iter().map(|p| p.port.clone()).collect());
        for (name, port) in names.iter().zip(ports) {
            self.bind_out((id.clone(), port), name.as_deref())?;
        }
        Ok(())
    }

    // ------------------------------------------------------------ statements
    fn ports_of(&self, name: &str, args: &[Arg], outs: &[Option<String>]) -> (Vec<PortEntry>, Vec<PortEntry>) {
        let sig = self.env.and_then(|e| e.resolve(name).found()).map(|r| r.signature.into_owned());
        let mut ins = Vec::with_capacity(args.len());
        let mut pos_i = 0;
        for a in args {
            let (mut entry, ptype) = match &a.key {
                None => {
                    let port = sig.as_ref().and_then(|s| s.inputs.get(pos_i));
                    let entry = PortEntry::named(&port.map_or(format!("in{pos_i}"), |p| p.name.clone()));
                    pos_i += 1;
                    (entry, port.map(|p| p.ty.clone()))
                }
                Some(key) => {
                    let ptype = sig.as_ref().and_then(|s| s.input(key)).map(|p| p.ty.clone());
                    (PortEntry { keyword: true, ..PortEntry::named(key) }, ptype)
                }
            };
            if let Some(t) = ptype.filter(|t| !t.is_any()) {
                entry.ty = Some(type_text(Some(&t)));
            }
            if let Expr::Literal(v) = &a.value {
                entry.value = Some(json_literal(v));
            }
            ins.push(entry);
        }
        let outs = outs
            .iter()
            .enumerate()
            .map(|(i, o)| {
                let port = sig.as_ref().and_then(|s| s.outputs.get(i));
                let ty = port.map(|p| &p.ty).filter(|t| !t.is_any()).map(|t| type_text(Some(t)));
                self.out_entry(&port.map_or(format!("out{i}"), |p| p.name.clone()), o.as_deref(), ty)
            })
            .collect();
        (ins, outs)
    }

    fn simple(&mut self, s: &'a Stmt, on_chain: bool) -> Result<usize> {
        let ctrl = |g: GNode| if on_chain { g.ctrl(&["in"], &["out"]) } else { g.ctrl(&[], &[]) };
        match &s.kind {
            Kind::Call { name, args, outs } => {
                let (ins, outs) = self.ports_of(name, args, outs);
                let g =
                    GNode { name: Some(name.clone()), inputs: Some(ins), outputs: Some(outs), ..GNode::new("call") };
                self.node(ctrl(g), name, Some(s))
            }
            // `x = 10` / `x = y`: the assign command, value in, variable out.
            Kind::Assign { target, value, ty } => {
                let mut input = PortEntry::named("value");
                if let Expr::Literal(v) = value {
                    input.value = Some(json_literal(v));
                }
                let out = self.out_entry("value", Some(target), ty.as_ref().map(write_type));
                let g = GNode { inputs: Some(vec![input]), outputs: Some(vec![out]), ..GNode::new("assign") };
                self.node(ctrl(g), "assign", Some(s))
            }
            _ => Err(KirError::Value("@dataflow blocks hold only assignments and calls".into())),
        }
    }

    fn wire_simple_inputs(&mut self, s: &'a Stmt, n: usize) -> Result<()> {
        let Some(&cfg_n) = self.cfg.node_of.get(&s.uid) else { return Ok(()) };
        let id = self.id(n);
        match &s.kind {
            Kind::Call { args, .. } => {
                let ports: Vec<String> =
                    self.nodes[n].inputs.as_ref().map_or(vec![], |i| i.iter().map(|p| p.port.clone()).collect());
                for (a, port) in args.iter().zip(ports) {
                    if let Expr::Name(x) = &a.value {
                        self.wire_read(cfg_n, x, (id.clone(), port))?;
                    }
                }
            }
            Kind::Assign { value: Expr::Name(x), .. } => self.wire_read(cfg_n, x, port_ref(&id, "value"))?,
            _ => {}
        }
        Ok(())
    }

    fn block(&mut self, stmts: &'a [Stmt], incoming: Vec<PortRef>) -> Result<Vec<PortRef>> {
        self.stack.push(stmts);
        let r = self.block_inner(stmts, incoming);
        self.stack.pop();
        r
    }

    fn block_inner(&mut self, stmts: &'a [Stmt], mut incoming: Vec<PortRef>) -> Result<Vec<PortRef>> {
        let mut local: HashMap<&'a str, &'a Stmt> = HashMap::new();
        for s in stmts {
            if let Kind::Namespace { label, .. } = &s.kind {
                local.insert(label, s);
            }
        }
        for s in stmts {
            match &s.kind {
                Kind::Def(_) | Kind::TypeHints { .. } => continue,
                Kind::Namespace { .. } => {
                    if !self.emitted.contains(&s.uid) {
                        if self
                            .cfg
                            .owners
                            .get(&s.uid)
                            .is_some_and(|owners| owners.iter().any(|owner| matches!(owner.kind, Kind::Collect { .. })))
                        {
                            continue;
                        }
                        // Never entered: keep it as an unreachable labelled chain.
                        let m = self.labelled_merge(s, None)?;
                        let ends = self.namespace(s, vec![port_ref(&m, "out")])?;
                        self.pending.entry(s.uid).or_default().extend(ends);
                    }
                    incoming.extend(self.pending.remove(&s.uid).unwrap_or_default());
                }
                Kind::Assign { .. } | Kind::Call { .. } => {
                    let n = self.simple(s, true)?;
                    self.wire_simple_inputs(s, n)?;
                    let id = self.id(n);
                    self.join(incoming, port_ref(&id, "in"))?;
                    self.bind_outs(s, n)?;
                    incoming = vec![port_ref(&id, "out")];
                }
                Kind::Dataflow { body } => {
                    // The members sit in the block's region; its owner is the dataflow node
                    let region = self.regions.len();
                    let rid = format!("{}/body", self.paths[&s.uid].1);
                    let outer = self.open_region(rid, "dataflow", None, None);
                    let mut members = Vec::with_capacity(body.len());
                    for inner in body {
                        members.push(self.simple(inner, false)?);
                    }
                    for (inner, &m) in body.iter().zip(&members) {
                        self.wire_simple_inputs(inner, m)?;
                        self.bind_outs(inner, m)?;
                    }
                    self.region = outer;
                    let ids: Vec<String> = members.iter().map(|&m| self.id(m)).collect();
                    let g = GNode::new("dataflow").props(vec![("members", Json::strs(&ids))]).ctrl(&["in"], &["out"]);
                    let g = self.node(g, "dataflow", Some(s))?;
                    let gid = self.id(g);
                    self.regions[region].owner = Some((gid.clone(), None));
                    self.join(incoming, port_ref(&gid, "in"))?;
                    incoming = vec![port_ref(&gid, "out")];
                }
                Kind::Branch { cond, true_label, false_label } => {
                    let labels = Json::Object(vec![
                        ("true".into(), Json::str(true_label)),
                        ("false".into(), Json::str(false_label)),
                    ]);
                    let g = GNode::new("branch").props(vec![("labels", labels)]);
                    let g =
                        GNode { inputs: Some(vec![PortEntry::named("cond")]), ..g }.ctrl(&["in"], &["true", "false"]);
                    let n = self.node(g, "branch", Some(s))?;
                    let id = self.id(n);
                    self.read_expr(s, cond, port_ref(&id, "cond"), n)?;
                    self.join(incoming, port_ref(&id, "in"))?;
                    incoming = vec![];
                    for (port, label) in [("true", true_label), ("false", false_label)] {
                        self.enter(&local, label, port_ref(&id, port))?;
                    }
                }
                Kind::Switch { value, cases, default } => {
                    let mut ports: Vec<String> = (0..cases.len()).map(|i| format!("case_{i}")).collect();
                    let mut labels: Vec<&String> = cases.iter().map(|(_, l)| l).collect();
                    if let Some(d) = default {
                        ports.push("default".into());
                        labels.push(d);
                    }
                    let label_map =
                        Json::Object(ports.iter().cloned().zip(labels.iter().map(|l| Json::str(*l))).collect());
                    let case_values = Json::Array(cases.iter().map(|(v, _)| json_literal(v)).collect());
                    let g = GNode::new("switch").props(vec![("cases", case_values), ("labels", label_map)]);
                    let port_strs: Vec<&str> = ports.iter().map(String::as_str).collect();
                    let g = GNode { inputs: Some(vec![PortEntry::named("value")]), ..g }.ctrl(&["in"], &port_strs);
                    let n = self.node(g, "switch", Some(s))?;
                    let id = self.id(n);
                    self.read_expr(s, value, port_ref(&id, "value"), n)?;
                    self.join(incoming, port_ref(&id, "in"))?;
                    incoming = vec![];
                    for (port, label) in ports.iter().zip(labels) {
                        self.enter(&local, label, port_ref(&id, port))?;
                    }
                }
                Kind::Parallel { labels } => {
                    let ports: Vec<String> = (0..labels.len()).map(|i| format!("out_{i}")).collect();
                    let label_map = Json::Object(ports.iter().cloned().zip(labels.iter().map(Json::str)).collect());
                    let port_strs: Vec<&str> = ports.iter().map(String::as_str).collect();
                    let g = GNode::new("parallel").props(vec![("labels", label_map)]).ctrl(&["in"], &port_strs);
                    let n = self.node(g, "parallel", Some(s))?;
                    let id = self.id(n);
                    self.join(incoming, port_ref(&id, "in"))?;
                    incoming = vec![];
                    for (port, label) in ports.iter().zip(labels) {
                        if let Some(&ns) = local.get(label.as_str()) {
                            self.emitted.insert(ns.uid);
                            let ends = self.namespace(ns, vec![port_ref(&id, port)])?;
                            incoming.extend(ends);
                        }
                    }
                }
                Kind::Each { items, item, index, label, has_index }
                | Kind::Collect { items, item, index, label, has_index, .. } => {
                    let collect = match &s.kind {
                        Kind::Collect { value, target, .. } => Some((value, target)),
                        _ => None,
                    };
                    let kind = if collect.is_some() { "collect" } else { "each" };
                    let mut g = GNode::new(kind).props(vec![
                        ("label", Json::str(label)),
                        ("item", Json::opt_str(item.as_deref())),
                        ("index", Json::opt_str(index.as_deref())),
                        ("has_index", Json::Bool(*has_index)),
                    ]);
                    let mut outputs = vec![
                        self.out_entry("item", item.as_deref(), None),
                        self.out_entry("index", index.as_deref(), None),
                    ];
                    let mut inputs = vec![PortEntry::named("items")];
                    if let Some((_, target)) = collect {
                        g.props.as_mut().unwrap().insert("target", Json::str(target));
                        inputs.push(PortEntry { deferred: Some("body_end"), ..PortEntry::named("value") });
                        outputs.push(self.out_entry("results", Some(target), None));
                    }
                    let g = GNode { inputs: Some(inputs), outputs: Some(outputs), ..g }
                        .ctrl(&["in", "next"], &["body", "done"]);
                    let n = self.node(g, kind, Some(s))?;
                    let id = self.id(n);
                    self.read_expr(s, items, port_ref(&id, "items"), n)?;
                    self.join(incoming, port_ref(&id, "in"))?;
                    self.bind_out(port_ref(&id, "item"), item.as_deref())?;
                    self.bind_out(port_ref(&id, "index"), index.as_deref())?;
                    if let Some((_, target)) = collect {
                        self.bind_out(port_ref(&id, "results"), Some(target))?;
                    }
                    if let Some(&ns) = local.get(label.as_str()) {
                        self.emitted.insert(ns.uid);
                        let ends = self.namespace(ns, vec![port_ref(&id, "body")])?;
                        self.join(ends, port_ref(&id, "next"))?;
                    }
                    if let Some((value, _)) = collect {
                        match value {
                            Expr::Literal(value) => {
                                self.nodes[n].inputs.as_mut().unwrap()[1].value = Some(json_literal(value))
                            }
                            Expr::Name(name) => {
                                self.wire_read(self.cfg.samples[&s.uid], name, port_ref(&id, "value"))?
                            }
                        }
                    }
                    incoming = vec![port_ref(&id, "done")];
                }
                Kind::Jump { label } => {
                    let is_entry = incoming.is_empty()
                        && self.cfg.succ[self.cfg.entry]
                            .iter()
                            .any(|(node, _)| self.cfg.node_of.get(&s.uid) == Some(node));
                    let edge_start = self.edges.len();
                    let edge_end;
                    let Some(target) = self.find_namespace(label) else {
                        incoming = vec![];
                        continue;
                    };
                    if !self.merges.contains_key(label) {
                        if self.emitted.contains(&target.uid) {
                            return Err(KirError::Graph(format!(
                                "namespace `{label}` is entered both by a builtin and by jump; a graph cannot draw that"
                            )));
                        }
                        let m = self.labelled_merge(target, Some(s))?;
                        self.join(incoming, port_ref(&m, "in_0"))?;
                        edge_end = self.edges.len();
                        let ends = self.namespace(target, vec![port_ref(&m, "out")])?;
                        self.pending.entry(target.uid).or_default().extend(ends);
                    } else {
                        self.loop_back(label, incoming);
                        edge_end = self.edges.len();
                    }
                    if is_entry {
                        let node = &mut self.nodes[self.index[&self.merges[label]]];
                        node.entry = true;
                        if let Some(origin) = &s.origin {
                            node.origin = Some(origin_json(origin));
                        }
                    }
                    if let Some(origin) = &s.origin {
                        let mid = &self.merges[label];
                        for edge in &mut self.edges[edge_start..edge_end] {
                            if edge.kind == "ctrl" && &edge.to.0 == mid {
                                edge.origin = Some(origin_json(origin));
                            }
                        }
                    }
                    incoming = vec![];
                }
                Kind::Try { body, handler, error_name } => {
                    let outputs = match error_name {
                        Some(e) => vec![self.out_entry("error", Some(e), None)],
                        None => vec![],
                    };
                    let g = GNode::new("try").props(vec![("error_name", Json::opt_str(error_name.as_deref()))]);
                    let g = GNode { outputs: Some(outputs), ..g }.ctrl(&["in"], &["try", "except"]);
                    let n = self.node(g, "try", Some(s))?;
                    let id = self.id(n);
                    self.join(incoming, port_ref(&id, "in"))?;
                    self.bind_out(port_ref(&id, "error"), error_name.as_deref())?;
                    let base = self.paths[&s.uid].1.clone();
                    let owner = |port: &str| Some((id.clone(), Some(port.to_string())));
                    let outer = self.open_region(format!("{base}/body"), "try", owner("try"), None);
                    let a = self.block(body, vec![port_ref(&id, "try")])?;
                    self.region = outer.clone();
                    self.open_region(format!("{base}/handler"), "try", owner("except"), None);
                    let b = self.block(handler, vec![port_ref(&id, "except")])?;
                    self.region = outer;
                    incoming = a;
                    incoming.extend(b);
                }
            }
        }
        Ok(incoming)
    }

    fn read_expr(&mut self, s: &'a Stmt, e: &Expr, target: PortRef, n: usize) -> Result<()> {
        match e {
            Expr::Literal(v) => {
                if let Some(entry) = self.nodes[n].inputs.as_mut().and_then(|i| i.first_mut()) {
                    entry.value = Some(json_literal(v));
                }
                Ok(())
            }
            Expr::Name(x) => match self.cfg.node_of.get(&s.uid).copied() {
                Some(cfg_n) => self.wire_read(cfg_n, x, target),
                None => Ok(()),
            },
        }
    }

    fn labelled_merge(&mut self, ns: &'a Stmt, stmt: Option<&'a Stmt>) -> Result<String> {
        let Kind::Namespace { label, .. } = &ns.kind else { unreachable!("a namespace") };
        let g = GNode::new("merge").props(vec![("label", Json::str(label))]).ctrl(&["in_0"], &["out"]);
        let m = self.node(g, "merge", stmt)?;
        let mid = self.id(m);
        self.merges.insert(label.clone(), mid.clone());
        self.emitted.insert(ns.uid);
        Ok(mid)
    }

    fn loop_back(&mut self, label: &str, incoming: Vec<PortRef>) {
        let mid = self.merges[label].clone();
        let m = self.index[&mid];
        for p in incoming {
            let ctrl_in = self.nodes[m].ctrl_in.get_or_insert_with(Vec::new);
            let port = format!("in_{}", ctrl_in.len());
            ctrl_in.push(port.clone());
            self.ctrl(p, (mid.clone(), port));
        }
    }

    fn enter(&mut self, local: &HashMap<&'a str, &'a Stmt>, label: &str, src: PortRef) -> Result<()> {
        let Some(&ns) = local.get(label) else { return Ok(()) };
        self.emitted.insert(ns.uid);
        let ends = self.namespace(ns, vec![src])?;
        self.pending.entry(ns.uid).or_default().extend(ends);
        Ok(())
    }

    fn namespace(&mut self, ns: &'a Stmt, incoming: Vec<PortRef>) -> Result<Vec<PortRef>> {
        if let Some(origin) = &ns.origin {
            for (nid, port) in &incoming {
                let node = &mut self.nodes[self.index[nid]];
                node.namespace_origins.get_or_insert_with(|| Json::Object(vec![])).insert(port, origin_json(origin));
            }
        }
        let Kind::Namespace { body, label } = &ns.kind else { unreachable!("a namespace") };

        // The body's region is owned by the port that enters it, of the owner's kind
        let (node, port) = incoming[0].clone();
        let kind = self.nodes[self.index[&node]].kind;
        let rid = self.paths[&ns.uid].0.clone();
        let outer = self.open_region(rid, kind, Some((node, Some(port))), Some(label.clone()));
        let r = self.block(body, incoming);
        self.region = outer;
        r
    }

    /// Like `jump`: the current block first, then each enclosing block.
    fn find_namespace(&self, label: &str) -> Option<&'a Stmt> {
        for stmts in self.stack.iter().rev() {
            for s in stmts.iter() {
                if matches!(&s.kind, Kind::Namespace { label: l, .. } if l == label) {
                    return Some(s);
                }
            }
        }
        None
    }

    // ------------------------------------------------------------ whole graph
    fn build(mut self) -> Result<Json> {
        let is_main = self.name == "main";
        let mut start = vec![];
        if !is_main {
            let outs = self
                .params
                .iter()
                .map(|p| self.out_entry(&p.name, Some(&p.name), p.ty.as_ref().map(write_type)))
                .collect();
            let g = GNode { id: "inputs".into(), outputs: Some(outs), ..GNode::new("inputs") }.ctrl(&[], &["out"]);
            self.push(g);
            self.ids.insert("inputs".into());
            start = vec![port_ref("inputs", "out")];
            for p in self.params {
                self.bind_out(port_ref("inputs", &p.name), Some(&p.name))?;
            }
        }
        let end = self.block(self.body, start)?;
        if !is_main {
            let ins = self
                .outputs
                .iter()
                .map(|o| PortEntry { ty: o.ty.as_ref().map(write_type), ..PortEntry::named(&o.name) })
                .collect();
            let g = GNode { id: "outputs".into(), inputs: Some(ins), ..GNode::new("outputs") }.ctrl(&["in"], &[]);
            self.push(g);
            self.ids.insert("outputs".into());
            self.join(end, port_ref("outputs", "in"))?;
            for o in self.outputs {
                self.wire_read(self.cfg.exit, &o.name, port_ref("outputs", &o.name))?;
            }
        }
        if self.variables {
            self.resolve_variables()?;
        }
        self.edges
            .sort_by(|a, b| (&a.to.0, &a.to.1, &a.from.0, &a.from.1).cmp(&(&b.to.0, &b.to.1, &b.from.0, &b.from.1)));
        let mut g = vec![
            ("name".to_string(), Json::str(&self.name)),
            ("nodes".to_string(), Json::Array(self.nodes.iter().map(GNode::to_json).collect())),
            ("edges".to_string(), Json::Array(self.edges.iter().map(Edge::to_json).collect())),
        ];
        if !self.regions.is_empty() {
            g.push(("regions".into(), Json::Array(self.regions.iter().map(Region::to_json).collect())));
        }
        if !is_main {
            let mut params = Vec::with_capacity(self.params.len());
            for p in self.params {
                let mut o = vec![("name".to_string(), Json::str(&p.name))];
                if let Some(t) = &p.ty {
                    o.push(("type".into(), Json::str(write_type(t))));
                }
                if let Some(Expr::Literal(v)) = &p.default {
                    o.push(("default".into(), json_literal(v)));
                }
                params.push(Json::Object(o));
            }
            let outputs = self
                .outputs
                .iter()
                .map(|o| {
                    let mut e = vec![("name".to_string(), Json::str(&o.name))];
                    if let Some(t) = &o.ty {
                        e.push(("type".into(), Json::str(write_type(t))));
                    }
                    Json::Object(e)
                })
                .collect();
            g.push(("params".into(), Json::Array(params)));
            g.push(("outputs".into(), Json::Array(outputs)));
        }
        Ok(Json::Object(g))
    }
}

/// How a graph draws data: `Wires` wires a read straight to its only write;
/// `Variables` draws every read as a `get` node and every write as a `set` node.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum DataStyle {
    #[default]
    Wires,
    Variables,
}

impl DataStyle {
    pub const NAMES: [&'static str; 2] = ["wires", "variables"];

    pub fn parse(name: &str) -> Result<DataStyle> {
        match name {
            "wires" => Ok(DataStyle::Wires),
            "variables" => Ok(DataStyle::Variables),
            _ => Err(KirError::Value(format!(
                "unknown data style {}; known: {}",
                str_repr(name),
                str_list_repr(&DataStyle::NAMES)
            ))),
        }
    }
}

/// The graph view of a program.
pub fn to_graph(program: &Program, env: Option<&NodeEnv>, data: DataStyle) -> Result<Json> {
    let mut graphs = vec![Scope::new(env, "main", &program.body, &[], &[], data, "body").build()?];
    for (index, s) in program.body.iter().enumerate() {
        if let Kind::Def(d) = &s.kind {
            let prefix = format!("body/{index}/body");
            let mut graph = Scope::new(env, &d.name, &d.body, &d.params, &d.outputs, data, &prefix).build()?;
            if let Some(origin) = &s.origin {
                graph.insert("origin", origin_json(origin));
            }
            graphs.push(graph);
        }
    }
    let uses = program
        .uses
        .iter()
        .map(|u| {
            Json::Object(vec![
                ("library".into(), Json::str(&u.library)),
                ("alias".into(), Json::opt_str(u.alias.as_deref())),
            ])
        })
        .collect();
    let mut out = vec![
        ("kirgraph".to_string(), Json::int(FORMAT)),
        ("uses".to_string(), Json::Array(uses)),
        ("graphs".to_string(), Json::Array(graphs)),
    ];
    if !program.imports.is_empty() {
        out.push((
            "imports".into(),
            Json::Array(
                program
                    .imports
                    .iter()
                    .map(|i| {
                        Json::Object(vec![
                            ("module".into(), Json::str(&i.module)),
                            ("alias".into(), Json::str(&i.alias)),
                        ])
                    })
                    .collect(),
            ),
        ));
    }
    if !program.exports.is_empty() {
        out.push(("exports".into(), Json::strs(&program.exports)));
    }
    if let Some(mode) = program.mode.as_deref().filter(|m| !m.is_empty()) {
        out.push(("mode".into(), Json::str(mode)));
    }
    let entries: Vec<Json> = program
        .body
        .iter()
        .filter_map(|s| match &s.kind {
            Kind::TypeHints { entries } => Some(entries),
            _ => None,
        })
        .flatten()
        .map(|e| {
            Json::Object(vec![
                ("name".into(), Json::str(&e.name)),
                ("inputs".into(), Json::Array(e.inputs.iter().map(|t| Json::str(write_type(t))).collect())),
                ("outputs".into(), Json::Array(e.outputs.iter().map(|t| Json::str(write_type(t))).collect())),
            ])
        })
        .collect();
    let has_hints = program.body.iter().any(|s| matches!(s.kind, Kind::TypeHints { .. }));
    if has_hints {
        out.push(("typehints".into(), Json::Array(entries)));
    }
    let hints: Vec<&Stmt> = program.body.iter().filter(|s| matches!(s.kind, Kind::TypeHints { .. })).collect();
    if hints.iter().any(|s| s.origin.is_some()) {
        out.push((
            "typehint_groups".into(),
            Json::Array(
                hints
                    .iter()
                    .map(|s| {
                        let Kind::TypeHints { entries } = &s.kind else { unreachable!() };
                        let mut group = Json::Object(vec![("count".into(), Json::Int(entries.len().into()))]);
                        if let Some(origin) = &s.origin {
                            group.insert("origin", origin_json(origin));
                        }
                        group
                    })
                    .collect(),
            ),
        ));
    }
    Ok(Json::Object(out))
}
