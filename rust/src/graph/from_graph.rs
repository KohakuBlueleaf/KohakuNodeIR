//! Graph view -> text: rebuild KIR text from node graphs (graph.md).
//!
//! The walk follows control edges. A branch-like node (branch, switch,
//! parallel, try) gets one namespace per output port; its arms stop at the
//! first node every arm reaches (the join), and the text continues from there.
//! A labelled merge is a loop entry: `()jump(`L`)` + `L:`, with edges back
//! into it written as jumps; when all paths leaving the loop meet at one node,
//! the text continues there after the namespace.

use std::collections::{HashMap, HashSet, VecDeque};

use crate::errors::{KirError, Result};
use crate::origins::origin_from_json;
use crate::sig::types::parse_type;
use crate::syntax::ast::{
    Arg, Def, Directives, Expr, Import, Kind, Origin, OutParam, Param, Program, Stmt, TypeExpr, TypeHintEntry, Use,
};
use crate::syntax::value::Value;
use crate::util::json::Json;
use crate::util::pyfmt::{float_repr, str_repr};
use num_traits::ToPrimitive;

type PortRef = (String, String);

fn gerr(m: impl Into<String>) -> KirError {
    KirError::Graph(m.into())
}

fn key<'j>(j: &'j Json, k: &str) -> Result<&'j Json> {
    j.get(k).ok_or_else(|| gerr(format!("missing key '{k}' in {}", j.dumps())))
}

fn string<'j>(j: &'j Json, k: &str) -> Result<&'j str> {
    key(j, k)?.as_str().ok_or_else(|| gerr(format!("'{k}' must be a string in {}", j.dumps())))
}

fn array<'j>(j: &'j Json, k: &str) -> Result<&'j [Json]> {
    key(j, k)?.as_array().map(Vec::as_slice).ok_or_else(|| gerr(format!("'{k}' must be a list in {}", j.dumps())))
}

/// `j.get(k, [])` for a list.
fn opt_array<'j>(j: &'j Json, k: &str) -> Result<&'j [Json]> {
    match j.get(k) {
        None => Ok(&[]),
        Some(_) => array(j, k),
    }
}

fn opt_string(j: Option<&Json>) -> Result<Option<String>> {
    match j {
        None | Some(Json::Null) => Ok(None),
        Some(Json::Str(s)) => Ok(Some(s.clone())),
        Some(other) => Err(gerr(format!("expected a string or null, got {}", other.dumps()))),
    }
}

fn type_of(j: &Json) -> Result<Option<TypeExpr>> {
    match j.get("type") {
        Some(t) if t.truthy() => {
            let text = t.as_str().ok_or_else(|| gerr("'type' must be a string"))?;
            Ok(Some(parse_type(text).map_err(gerr)?))
        }
        _ => Ok(None),
    }
}

/// A graph literal as a value: tagged tuples and dicts decoded.
pub fn decode_literal(v: &Json) -> Result<Value> {
    Ok(match v {
        Json::Array(items) => Value::List(items.iter().map(decode_literal).collect::<Result<_>>()?),
        Json::Object(_) => {
            if let Some(t) = v.get("tuple") {
                let items = t.as_array().ok_or_else(|| gerr("'tuple' must be a list"))?;
                Value::Tuple(items.iter().map(decode_literal).collect::<Result<_>>()?)
            } else if let Some(d) = v.get("dict") {
                let pairs = d.as_object().ok_or_else(|| gerr("'dict' must be an object"))?;
                Value::Dict(
                    pairs
                        .iter()
                        .map(|(k, x)| Ok((Value::Str(k.clone()), decode_literal(x)?)))
                        .collect::<Result<_>>()?,
                )
            } else if let Some(p) = v.get("pairs") {
                let mut pairs = Vec::new();
                for kv in p.as_array().ok_or_else(|| gerr("'pairs' must be a list"))? {
                    let kv = kv.as_array().filter(|kv| kv.len() == 2).ok_or_else(|| gerr("a pair is [key, value]"))?;
                    Value::dict_set(&mut pairs, decode_literal(&kv[0])?, decode_literal(&kv[1])?).map_err(gerr)?;
                }
                Value::Dict(pairs)
            } else {
                return Err(gerr(format!("bad literal {}", v.dumps())));
            }
        }
        scalar => finite(Value::from_json(scalar))?,
    })
}

/// `v` itself, after checking that no float in it (or in its dict values) is infinite or NaN.
fn finite(v: Value) -> Result<Value> {
    fn check(v: &Value) -> Result<()> {
        match v {
            Value::Float(f) if !f.is_finite() => Err(gerr(format!("{} has no KIR literal", float_repr(*f)))),
            Value::List(items) | Value::Tuple(items) => items.iter().try_for_each(check),
            Value::Dict(pairs) => pairs.iter().try_for_each(|(_, x)| check(x)),
            _ => Ok(()),
        }
    }
    check(&v)?;
    Ok(v)
}

/// A `@meta` value: a JSON list is a tuple (positions, sizes).
fn meta_value(v: &Json) -> Result<Value> {
    finite(match v {
        Json::Array(items) => Value::Tuple(items.iter().map(Value::from_json).collect()),
        other => Value::from_json(other),
    })
}

struct GraphView<'g> {
    with_meta: bool,
    nodes: HashMap<&'g str, &'g Json>,
    order: Vec<&'g str>,
    ctrl_out: HashMap<PortRef, PortRef>,
    ctrl_origins: HashMap<PortRef, Origin>,
    ctrl_in: HashMap<&'g str, Vec<PortRef>>,
    data_in: HashMap<PortRef, PortRef>,
    rename: HashMap<PortRef, String>,
    members: HashSet<String>,
    emitted: HashSet<String>,
}

fn kind_of(n: &Json) -> Result<&str> {
    string(n, "kind")
}

fn props(n: &Json) -> Option<&Json> {
    n.get("props")
}

fn prop<'j>(n: &'j Json, k: &str) -> Option<&'j Json> {
    props(n).and_then(|p| p.get(k))
}

impl<'g> GraphView<'g> {
    fn new(g: &'g Json, with_meta: bool) -> Result<Self> {
        let list = array(g, "nodes")?;
        let mut nodes = HashMap::new();
        let mut order = Vec::with_capacity(list.len());
        for n in list {
            let id = string(n, "id")?;
            nodes.insert(id, n);
            order.push(id);
        }
        let mut v = GraphView {
            with_meta,
            ctrl_in: nodes.keys().map(|&k| (k, Vec::new())).collect(),
            nodes,
            order,
            ctrl_out: HashMap::new(),
            ctrl_origins: HashMap::new(),
            data_in: HashMap::new(),
            rename: HashMap::new(),
            members: HashSet::new(),
            emitted: HashSet::new(),
        };
        for e in array(g, "edges")? {
            let end = |k: &str| -> Result<PortRef> {
                let p = key(e, k)?;
                Ok((string(p, "node")?.to_string(), string(p, "port")?.to_string()))
            };
            let (src, dst) = (end("from")?, end("to")?);
            if !v.nodes.contains_key(src.0.as_str()) || !v.nodes.contains_key(dst.0.as_str()) {
                return Err(gerr(format!("edge {} names an unknown node", e.dumps())));
            }
            if string(e, "kind")? == "ctrl" {
                v.ctrl_out.insert(src.clone(), dst.clone());
                if let Some(origin) = origin_from_json(e.get("origin"))? {
                    v.ctrl_origins.insert(src.clone(), origin);
                }
                let (&k, _) = v.nodes.get_key_value(dst.0.as_str()).expect("checked");
                v.ctrl_in.get_mut(k).expect("every node").push(src);
            } else {
                if v.data_in.contains_key(&dst) {
                    return Err(gerr(format!("input ({}, {}) has two data edges", str_repr(&dst.0), str_repr(&dst.1))));
                }
                v.data_in.insert(dst, src);
            }
        }
        for n in list {
            // A `set` variable node names the output port wired into it.
            if kind_of(n)? == "set" {
                let nid = string(n, "id")?.to_string();
                if let Some(src) = v.data_in.get(&(nid, "value".to_string())).cloned() {
                    let name = prop(n, "name").and_then(Json::as_str).ok_or_else(|| gerr("set node without name"))?;
                    match v.rename.get(&src) {
                        Some(old) if old != name => {
                            return Err(gerr(format!(
                                "output ({}, {}) feeds two variables: {} and {}",
                                str_repr(&src.0),
                                str_repr(&src.1),
                                str_repr(old),
                                str_repr(name)
                            )));
                        }
                        _ => {
                            v.rename.insert(src, name.to_string());
                        }
                    }
                }
            }
        }
        for n in list {
            if kind_of(n)? == "dataflow" {
                for m in prop(n, "members").and_then(Json::as_array).ok_or_else(|| gerr("dataflow without members"))? {
                    v.members.insert(m.as_str().ok_or_else(|| gerr("member ids are strings"))?.to_string());
                }
            }
        }
        Ok(v)
    }

    fn node(&self, nid: &str) -> Result<&'g Json> {
        self.nodes.get(nid).copied().ok_or_else(|| gerr(format!("unknown node '{nid}'")))
    }

    // ------------------------------------------------------------ names
    fn var(&self, src: &PortRef) -> Result<String> {
        if let Some(name) = self.rename.get(src) {
            return Ok(name.clone());
        }
        let n = self.node(&src.0)?;
        if kind_of(n)? == "get" {
            return Ok(prop(n, "name")
                .and_then(Json::as_str)
                .ok_or_else(|| gerr("get node without name"))?
                .to_string());
        }
        for p in opt_array(n, "outputs")? {
            if string(p, "port")? == src.1 {
                if let Some(var) = p.get("var").filter(|v| v.truthy()) {
                    return Ok(var.as_str().ok_or_else(|| gerr("'var' must be a string"))?.to_string());
                }
                break;
            }
        }
        Ok(format!("{}_{}", src.0, src.1))
    }

    fn expr(&self, nid: &str, port: &Json) -> Result<Option<Expr>> {
        if let Some(src) = self.data_in.get(&(nid.to_string(), string(port, "port")?.to_string())) {
            let producer = self.node(&src.0)?;
            if kind_of(producer)? == "value" {
                let value = prop(producer, "value").ok_or_else(|| gerr("value node without value"))?;
                return Ok(Some(Expr::Literal(decode_literal(value)?)));
            }
            return Ok(Some(Expr::Name(self.var(src)?)));
        }
        match port.get("value") {
            Some(v) => Ok(Some(Expr::Literal(decode_literal(v)?))),
            None => Ok(None),
        }
    }

    fn decorate(&self, mut s: Stmt, n: &Json) -> Result<Stmt> {
        if self.with_meta {
            let mut meta = Directives::new();
            meta.insert("node_id".into(), Value::from_json(key(n, "id")?));
            if let Some(m) = n.get("meta") {
                for (k, v) in m.as_object().ok_or_else(|| gerr("'meta' must be an object"))? {
                    meta.insert(k.clone(), meta_value(v)?);
                }
            }
            s.meta = meta;
        }
        let mut hint = Directives::new();
        if let Some(h) = n.get("hints") {
            for (k, v) in h.as_object().ok_or_else(|| gerr("'hints' must be an object"))? {
                hint.insert(k.clone(), finite(Value::from_json(v))?);
            }
        }
        s.hint = hint;
        s.origin = origin_from_json(n.get("origin"))?;
        Ok(s)
    }

    fn namespace(&self, label: String, body: Vec<Stmt>, n: &Json, port: &str) -> Result<Stmt> {
        let mut s = Stmt::new(Kind::Namespace { label, body }, None);
        s.origin = origin_from_json(n.get("namespace_origins").and_then(|o| o.get(port)))?;
        Ok(s)
    }

    // ------------------------------------------------------------ statements
    fn simple(&self, n: &Json) -> Result<Stmt> {
        let nid = string(n, "id")?;
        let kind = kind_of(n)?;
        if kind == "assign" {
            let out = array(n, "outputs")?.first().ok_or_else(|| gerr("assign node without output"))?;
            let ty = type_of(out)?;
            let input = array(n, "inputs")?.first().ok_or_else(|| gerr("assign node without input"))?;
            let value = self.expr(nid, input)?.unwrap_or(Expr::Literal(Value::None));
            let target = self.var(&(nid.to_string(), "value".to_string()))?;
            return self.decorate(Stmt::new(Kind::Assign { target, value, ty }, None), n);
        }
        let mut args = Vec::new();
        for port in opt_array(n, "inputs")? {
            let Some(e) = self.expr(nid, port)? else { continue };
            let keyword = port.get("keyword").is_some_and(Json::truthy);
            let key = if keyword { Some(string(port, "port")?.to_string()) } else { None };
            args.push(Arg { value: e, key });
        }
        let mut outs = Vec::new();
        for p in opt_array(n, "outputs")? {
            let k = (nid.to_string(), string(p, "port")?.to_string());
            if !self.rename.contains_key(&k) && p.get("var").is_some_and(Json::is_null) {
                outs.push(None);
            } else {
                outs.push(Some(self.var(&k)?));
            }
        }
        self.decorate(Stmt::new(Kind::Call { name: string(n, "name")?.to_string(), args, outs }, None), n)
    }

    /// The name a builtin's output port binds: its `set` node's, else the props'.
    fn bound(&self, nid: &str, port: &str, default: Option<&Json>) -> Result<Option<String>> {
        match self.rename.get(&(nid.to_string(), port.to_string())) {
            Some(name) => Ok(Some(name.clone())),
            None => opt_string(default),
        }
    }

    fn next_of(&self, nid: &str, port: &str) -> Option<String> {
        self.ctrl_out.get(&(nid.to_string(), port.to_string())).map(|d| d.0.clone())
    }

    // ------------------------------------------------------------ reachability
    fn succ(&self, nid: &str) -> Result<Vec<String>> {
        let n = self.node(nid)?;
        let mut out = Vec::new();
        for p in opt_array(n, "ctrl_out")? {
            let p = p.as_str().ok_or_else(|| gerr("control ports are strings"))?;
            if let Some(d) = self.next_of(nid, p) {
                out.push(d);
            }
        }
        Ok(out)
    }

    /// Nodes reachable from `start` in breadth-first order; `stop` nodes are not passed.
    fn reach(&self, start: Option<&str>, stop: &HashSet<String>) -> Result<Vec<String>> {
        let Some(start) = start else { return Ok(vec![]) };
        let mut seen = HashSet::from([start.to_string()]);
        let mut queue = VecDeque::from([start.to_string()]);
        let mut out = Vec::new();
        while let Some(nid) = queue.pop_front() {
            out.push(nid.clone());
            if stop.contains(&nid) {
                continue;
            }
            for s in self.succ(&nid)? {
                if seen.insert(s.clone()) {
                    queue.push_back(s);
                }
            }
        }
        Ok(out)
    }

    /// The first node every arm reaches inside the current region; None when arms never meet.
    fn join_of(&self, starts: &[Option<String>], stop: &HashSet<String>) -> Result<Option<String>> {
        if starts.is_empty() || starts.iter().any(Option::is_none) {
            return Ok(None);
        }
        let sets = starts
            .iter()
            .map(|s| Ok(self.reach(s.as_deref(), stop)?.into_iter().collect::<HashSet<_>>()))
            .collect::<Result<Vec<_>>>()?;
        for nid in self.reach(starts[0].as_deref(), stop)? {
            if sets.iter().all(|s| s.contains(&nid)) {
                return Ok(Some(nid));
            }
        }
        Ok(None)
    }

    /// The single node every path leaving the loop reaches first, if there is one.
    fn loop_exit(&self, merge: &str, stop: &HashSet<String>) -> Result<Option<String>> {
        let mut body: HashSet<String> = self.reach(self.next_of(merge, "out").as_deref(), stop)?.into_iter().collect();
        body.remove(merge);
        let mut back = HashSet::new();
        for nid in &body {
            if !stop.contains(nid) && self.reach(Some(nid), stop)?.iter().any(|x| x == merge) {
                back.insert(nid.clone());
            }
        }
        let mut exits = HashSet::new();
        for nid in &back {
            for s in self.succ(nid)? {
                if s != merge && !back.contains(&s) {
                    exits.insert(s);
                }
            }
        }
        Ok(if exits.len() == 1 { exits.into_iter().next() } else { None })
    }

    // ------------------------------------------------------------ chains
    fn chain_next(&mut self, nid: &str, port: &str, stop: &HashSet<String>) -> Result<Vec<Stmt>> {
        self.chain(self.next_of(nid, port), stop, self.ctrl_origins.get(&(nid.to_string(), port.to_string())).cloned())
    }

    fn chain(
        &mut self,
        start: Option<String>,
        stop: &HashSet<String>,
        mut incoming_origin: Option<Origin>,
    ) -> Result<Vec<Stmt>> {
        let mut out = Vec::new();
        let mut cur = start;
        while let Some(c) = cur.take() {
            let n = self.node(&c)?;
            let kind = kind_of(n)?;
            let label = if kind == "merge" { prop(n, "label").filter(|l| l.truthy()) } else { None };
            let label = label.map(|l| l.as_str().ok_or_else(|| gerr("labels are strings"))).transpose()?;
            if let (Some(l), true) = (label, self.emitted.contains(&c)) {
                let mut jump = Stmt::new(Kind::Jump { label: l.to_string() }, None);
                jump.origin = incoming_origin;
                out.push(jump);
                break;
            }
            if stop.contains(&c) {
                // Shared labelled joins retain explicit arm jumps independently of provenance.
                if let Some(label) = label {
                    let mut jump = Stmt::new(Kind::Jump { label: label.to_string() }, None);
                    jump.origin = incoming_origin;
                    out.push(jump);
                }
                break;
            }
            if kind == "merge" {
                let Some(label) = label else {
                    cur = self.next_of(&c, "out");
                    incoming_origin = self.ctrl_origins.get(&(c.clone(), "out".into())).cloned();
                    continue;
                };
                let mut jump = self.decorate(Stmt::new(Kind::Jump { label: label.to_string() }, None), n)?;
                if incoming_origin.is_some() {
                    jump.origin = incoming_origin.take();
                }
                out.push(jump);
                self.emitted.insert(c.clone());
                let exit = self.loop_exit(&c, stop)?;
                let mut inner_stop = stop.clone();
                inner_stop.insert(c.clone());
                inner_stop.extend(exit.clone());
                let body = self.chain_next(&c, "out", &inner_stop)?;
                out.push(self.namespace(label.to_string(), body, n, "out")?);
                cur = exit;
                incoming_origin = None;
                continue;
            }
            if self.emitted.contains(&c) {
                break;
            }
            self.emitted.insert(c.clone());
            let nxt = match kind {
                "call" | "assign" => {
                    out.push(self.simple(n)?);
                    self.next_of(&c, "out")
                }
                "dataflow" => {
                    let mut body = Vec::new();
                    for m in
                        prop(n, "members").and_then(Json::as_array).ok_or_else(|| gerr("dataflow without members"))?
                    {
                        body.push(self.simple(self.node(m.as_str().ok_or_else(|| gerr("member ids are strings"))?)?)?);
                    }
                    out.push(self.decorate(Stmt::new(Kind::Dataflow { body }, None), n)?);
                    self.next_of(&c, "out")
                }
                "each" | "collect" => {
                    let items_port = array(n, "inputs")?.first().ok_or_else(|| gerr("each node without input"))?;
                    let items = self.expr(&c, items_port)?.unwrap_or(Expr::Literal(Value::List(vec![])));
                    let label = prop(n, "label").and_then(Json::as_str).ok_or_else(|| gerr("each without label"))?;
                    let item = self.bound(&c, "item", prop(n, "item"))?;
                    let index = self.bound(&c, "index", prop(n, "index"))?;
                    let has_index = prop(n, "has_index").is_some_and(Json::truthy);
                    let each = if kind == "collect" {
                        let value_port = array(n, "inputs")?
                            .iter()
                            .find(|p| p.get("port").and_then(Json::as_str) == Some("value"))
                            .filter(|p| p.get("deferred").and_then(Json::as_str) == Some("body_end"))
                            .ok_or_else(|| gerr("collect requires a value input deferred to body_end"))?;
                        let value = self.expr(&c, value_port)?;
                        let target = self.bound(&c, "results", prop(n, "target"))?;
                        let (Some(value), Some(target)) = (value, target.filter(|s| !s.is_empty())) else {
                            return Err(gerr("collect requires a value expression and result target"));
                        };
                        Kind::Collect { items, item, index, label: label.to_string(), value, target, has_index }
                    } else {
                        Kind::Each { items, item, index, label: label.to_string(), has_index }
                    };
                    out.push(self.decorate(Stmt::new(each, None), n)?);
                    let mut inner_stop = stop.clone();
                    inner_stop.insert(c.clone());
                    let body = self.chain_next(&c, "body", &inner_stop)?;
                    out.push(self.namespace(label.to_string(), body, n, "body")?);
                    self.next_of(&c, "done")
                }
                "branch" | "switch" | "parallel" | "try" => self.branch_like(n, &c, kind, stop, &mut out)?,
                "inputs" => self.next_of(&c, "out"),
                "outputs" | "get" | "set" | "value" => None,
                other => return Err(gerr(format!("unknown node kind '{other}'"))),
            };
            incoming_origin = if matches!(kind, "call" | "assign" | "dataflow" | "inputs" | "each" | "collect") {
                self.ctrl_origins
                    .get(&(c.clone(), if matches!(kind, "each" | "collect") { "done" } else { "out" }.into()))
                    .cloned()
            } else {
                None
            };
            cur = nxt;
        }
        Ok(out)
    }

    fn branch_like(
        &mut self,
        n: &'g Json,
        c: &str,
        kind: &str,
        stop: &HashSet<String>,
        out: &mut Vec<Stmt>,
    ) -> Result<Option<String>> {
        let ports: Vec<&str> = array(n, "ctrl_out")?
            .iter()
            .map(|p| p.as_str().ok_or_else(|| gerr("control ports are strings")))
            .collect::<Result<_>>()?;
        let starts: Vec<Option<String>> = ports.iter().map(|p| self.next_of(c, p)).collect();
        let join = self.join_of(&starts, stop)?;
        let mut arm_stop = stop.clone();
        arm_stop.extend(join.clone());
        let labels = || prop(n, "labels").ok_or_else(|| gerr(format!("{kind} node without labels")));
        let label_of = |port: &str| -> Result<String> {
            Ok(labels()?
                .get(port)
                .and_then(Json::as_str)
                .ok_or_else(|| gerr(format!("no label for port '{port}'")))?
                .to_string())
        };
        let input = |what: &str| -> Result<Expr> {
            let port = array(n, "inputs")?.first().ok_or_else(|| gerr(format!("{kind} node without input")))?;
            self.expr(c, port)?.ok_or_else(|| gerr(format!("{kind} node has no {what}")))
        };
        match kind {
            "branch" => {
                let s = Kind::Branch {
                    cond: input("condition")?,
                    true_label: label_of("true")?,
                    false_label: label_of("false")?,
                };
                out.push(self.decorate(Stmt::new(s, None), n)?);
                for port in ["true", "false"] {
                    let body = self.chain_next(c, port, &arm_stop)?;
                    out.push(self.namespace(label_of(port)?, body, n, port)?);
                }
            }
            "switch" => {
                let mut cases = Vec::new();
                for (i, v) in prop(n, "cases")
                    .and_then(Json::as_array)
                    .ok_or_else(|| gerr("switch without cases"))?
                    .iter()
                    .enumerate()
                {
                    cases.push((decode_literal(v)?, label_of(&format!("case_{i}"))?));
                }
                let default = opt_string(labels()?.get("default"))?;
                let s = Kind::Switch { value: input("value")?, cases, default };
                out.push(self.decorate(Stmt::new(s, None), n)?);
                for port in &ports {
                    let body = self.chain_next(c, port, &arm_stop)?;
                    out.push(self.namespace(label_of(port)?, body, n, port)?);
                }
            }
            "parallel" => {
                let s = Kind::Parallel { labels: ports.iter().map(|p| label_of(p)).collect::<Result<_>>()? };
                out.push(self.decorate(Stmt::new(s, None), n)?);
                for port in &ports {
                    let body = self.chain_next(c, port, &arm_stop)?;
                    out.push(self.namespace(label_of(port)?, body, n, port)?);
                }
            }
            _ => {
                let error_name = self.bound(c, "error", prop(n, "error_name"))?;
                let body = self.chain_next(c, "try", &arm_stop)?;
                let handler = self.chain_next(c, "except", &arm_stop)?;
                out.push(self.decorate(Stmt::new(Kind::Try { body, handler, error_name }, None), n)?);
            }
        }
        Ok(join)
    }

    fn body(&mut self) -> Result<Vec<Stmt>> {
        let mut free: Vec<&'g str> = Vec::new();
        for &nid in &self.order {
            let n = self.node(nid)?;
            let kind = kind_of(n)?;
            if matches!(kind, "call" | "assign")
                && !n.get("ctrl_in").is_some_and(Json::truthy)
                && !self.members.contains(nid)
            {
                free.push(nid);
            }
        }
        let mut out = Vec::new();
        if !free.is_empty() {
            let body = free.iter().map(|nid| self.simple(self.node(nid)?)).collect::<Result<Vec<_>>>()?;
            out.push(Stmt::new(Kind::Dataflow { body }, None));
            self.emitted.extend(free.iter().map(|s| s.to_string()));
        }
        let free: HashSet<&str> = free.into_iter().collect();
        for nid in self.order.clone() {
            if self.emitted.contains(nid) || self.members.contains(nid) || free.contains(nid) {
                continue;
            }
            let n = self.node(nid)?;
            let kind = kind_of(n)?;
            if matches!(kind, "get" | "set" | "value" | "outputs") {
                continue;
            }
            // Back edges alone do not disqualify a root each/merge. An explicit
            // entry marker, not provenance, determines whether a merge executes.
            let primary =
                n.get("ctrl_in").and_then(Json::as_array).and_then(|ports| ports.first()).and_then(Json::as_str);
            let source_entry = matches!(kind, "each" | "collect" | "merge")
                && primary.is_some_and(|port| !self.ctrl_out.values().any(|dst| dst.0 == nid && dst.1 == port));
            if !self.ctrl_in[nid].is_empty() && kind != "inputs" && !source_entry {
                continue;
            }
            let label = if kind == "merge" { prop(n, "label").filter(|l| l.truthy()) } else { None };
            if kind == "merge" && label.is_none() {
                continue;
            }
            if kind == "merge" && n.get("entry") != Some(&Json::Bool(true)) {
                let Some(label) = label else { continue };
                let label = label.as_str().ok_or_else(|| gerr("labels are strings"))?.to_string();
                // A labelled merge nothing enters: a namespace never entered.
                self.emitted.insert(nid.to_string());
                let body = self.chain_next(nid, "out", &HashSet::from([nid.to_string()]))?;
                out.push(self.namespace(label, body, n, "out")?);
                continue;
            }
            out.extend(self.chain(Some(nid.to_string()), &HashSet::new(), None)?);
        }
        Ok(out)
    }
}

/// The canonical program of a graph view.
pub fn from_graph(graph: &Json, with_meta: bool) -> Result<Program> {
    let version = graph.get("kirgraph").map_or(Value::None, Value::from_json);
    if !version.py_eq(&Value::int(2)) {
        return Err(gerr(format!("unsupported kirgraph version {}", version.repr())));
    }
    let mut program = Program::default();
    for u in opt_array(graph, "uses")? {
        program.uses.push(Use { library: string(u, "library")?.to_string(), alias: opt_string(u.get("alias"))? });
    }
    for i in opt_array(graph, "imports")? {
        program
            .imports
            .push(Import { module: string(i, "module")?.to_string(), alias: string(i, "alias")?.to_string() });
    }
    for e in opt_array(graph, "exports")? {
        program.exports.push(e.as_str().ok_or_else(|| gerr("exports must be strings"))?.to_string());
    }
    program.mode = opt_string(graph.get("mode"))?;
    if graph.get("typehints").is_some_and(Json::truthy) || graph.get("typehint_groups").is_some_and(Json::truthy) {
        let mut entries = Vec::new();
        for h in opt_array(graph, "typehints")? {
            let types = |k: &str| -> Result<Vec<TypeExpr>> {
                array(h, k)?
                    .iter()
                    .map(|t| parse_type(t.as_str().ok_or_else(|| gerr("types are strings"))?).map_err(gerr))
                    .collect()
            };
            entries.push(TypeHintEntry {
                name: string(h, "name")?.to_string(),
                inputs: types("inputs")?,
                outputs: types("outputs")?,
            });
        }
        if graph.contains_key("typehint_groups") {
            let mut offset = 0;
            for group in array(graph, "typehint_groups")? {
                let count = match group.get("count") {
                    Some(Json::Int(n)) => n.to_usize(),
                    _ => None,
                }
                .filter(|&n| n <= entries.len() - offset)
                .ok_or_else(|| gerr("invalid typehint group count"))?;
                let mut stmt = Stmt::new(Kind::TypeHints { entries: entries[offset..offset + count].to_vec() }, None);
                stmt.origin = origin_from_json(group.get("origin"))?;
                program.body.push(stmt);
                offset += count;
            }
            if offset != entries.len() {
                return Err(gerr("typehint groups do not cover all entries"));
            }
        } else {
            program.body.push(Stmt::new(Kind::TypeHints { entries }, None));
        }
    }
    let mut main = None;
    for g in array(graph, "graphs")? {
        let name = string(g, "name")?;
        if name == "main" {
            main = Some(g);
            continue;
        }
        let mut rebuilt = GraphView::new(g, with_meta)?;
        let mut body = rebuilt.body()?;
        if rebuilt.nodes.contains_key("outputs") {
            for o in opt_array(g, "outputs")? {
                let oname = string(o, "name")?;
                if let Some(src) = rebuilt.data_in.get(&("outputs".to_string(), oname.to_string())) {
                    let v = rebuilt.var(src)?;
                    if v != oname {
                        body.push(Stmt::assign(oname, Expr::Name(v), None));
                    }
                }
            }
        }
        let mut params = Vec::new();
        for p in opt_array(g, "params")? {
            let default = match p.get("default") {
                Some(d) => Some(Expr::Literal(decode_literal(d)?)),
                None => None,
            };
            params.push(Param { name: string(p, "name")?.to_string(), ty: type_of(p)?, default });
        }
        let mut outputs = Vec::new();
        for o in opt_array(g, "outputs")? {
            outputs.push(OutParam { name: string(o, "name")?.to_string(), ty: type_of(o)? });
        }
        let mut def = Stmt::new(Kind::Def(Def { name: name.to_string(), params, outputs, body }), None);
        def.origin = origin_from_json(g.get("origin"))?;
        program.body.push(def);
    }
    if let Some(g) = main {
        program.body.extend(GraphView::new(g, with_meta)?.body()?);
    }
    Ok(program)
}
