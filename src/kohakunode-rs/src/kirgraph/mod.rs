//! KirGraph (Level 1 IR) — node-and-edge graph schema.
//!
//! Mirrors `kohakunode.kirgraph.schema` exactly.
//! JSON wire format uses nested `from`/`to` objects for edges:
//! `{"type":"data","from":{"node":"a","port":"out"},"to":{"node":"b","port":"in"}}`
//!
//! [`KirGraph::from_json`] and [`KirGraph::to_json`] are the public
//! (de)serialisation entry points.

pub mod compiler;
pub mod decompiler;

pub use decompiler::decompile;

#[cfg(feature = "pyo3")]
pub mod pyo3;

use serde::{
    de::{self, MapAccess, Visitor},
    ser::SerializeMap,
    Deserialize, Deserializer, Serialize, Serializer,
};
use std::collections::HashMap;

use crate::ast::Value;

// ---------------------------------------------------------------------------
// KGPort
// ---------------------------------------------------------------------------

/// A data port on a node (input or output).
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct KGPort {
    pub port: String,
    #[serde(default = "default_type")]
    pub r#type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub default: Option<Value>,
}

fn default_type() -> String {
    "any".to_string()
}

impl KGPort {
    pub fn new(port: impl Into<String>) -> Self {
        KGPort {
            port: port.into(),
            r#type: "any".to_string(),
            default: None,
        }
    }

    pub fn with_type(port: impl Into<String>, type_: impl Into<String>) -> Self {
        KGPort {
            port: port.into(),
            r#type: type_.into(),
            default: None,
        }
    }

    pub fn with_default(port: impl Into<String>, default: Value) -> Self {
        KGPort {
            port: port.into(),
            r#type: "any".to_string(),
            default: Some(default),
        }
    }
}

// ---------------------------------------------------------------------------
// KGEdge — custom (de)serialization for nested from/to objects
// ---------------------------------------------------------------------------

/// An edge connecting two ports across two nodes.
///
/// JSON wire format:
/// ```json
/// {"type":"data","from":{"node":"a","port":"out"},"to":{"node":"b","port":"in"}}
/// ```
#[derive(Clone, Debug, Default, PartialEq)]
pub struct KGEdge {
    /// "data" or "control"
    pub r#type: String,
    pub from_node: String,
    pub from_port: String,
    pub to_node: String,
    pub to_port: String,
}

impl Serialize for KGEdge {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        let mut map = s.serialize_map(Some(3))?;
        map.serialize_entry("type", &self.r#type)?;
        map.serialize_entry(
            "from",
            &serde_json::json!({"node": &self.from_node, "port": &self.from_port}),
        )?;
        map.serialize_entry(
            "to",
            &serde_json::json!({"node": &self.to_node, "port": &self.to_port}),
        )?;
        map.end()
    }
}

impl<'de> Deserialize<'de> for KGEdge {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct KGEdgeVisitor;
        impl<'de> Visitor<'de> for KGEdgeVisitor {
            type Value = KGEdge;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("a KGEdge object with nested from/to")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<KGEdge, A::Error> {
                let mut edge_type: Option<String> = None;
                let mut from: Option<serde_json::Value> = None;
                let mut to: Option<serde_json::Value> = None;
                while let Some(key) = map.next_key::<String>()? {
                    match key.as_str() {
                        "type" => edge_type = Some(map.next_value()?),
                        "from" => from = Some(map.next_value()?),
                        "to" => to = Some(map.next_value()?),
                        _ => {
                            let _ = map.next_value::<serde_json::Value>()?;
                        }
                    }
                }
                let from = from.ok_or_else(|| de::Error::missing_field("from"))?;
                let to = to.ok_or_else(|| de::Error::missing_field("to"))?;
                let from_node = from
                    .get("node")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| de::Error::custom("from.node missing or not a string"))?
                    .to_string();
                let from_port = from
                    .get("port")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| de::Error::custom("from.port missing or not a string"))?
                    .to_string();
                let to_node = to
                    .get("node")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| de::Error::custom("to.node missing or not a string"))?
                    .to_string();
                let to_port = to
                    .get("port")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| de::Error::custom("to.port missing or not a string"))?
                    .to_string();
                Ok(KGEdge {
                    r#type: edge_type.ok_or_else(|| de::Error::missing_field("type"))?,
                    from_node,
                    from_port,
                    to_node,
                    to_port,
                })
            }
        }
        d.deserialize_map(KGEdgeVisitor)
    }
}

impl KGEdge {
    pub fn control(
        from_node: impl Into<String>,
        from_port: impl Into<String>,
        to_node: impl Into<String>,
        to_port: impl Into<String>,
    ) -> Self {
        KGEdge {
            r#type: "control".to_string(),
            from_node: from_node.into(),
            from_port: from_port.into(),
            to_node: to_node.into(),
            to_port: to_port.into(),
        }
    }

    pub fn data(
        from_node: impl Into<String>,
        from_port: impl Into<String>,
        to_node: impl Into<String>,
        to_port: impl Into<String>,
    ) -> Self {
        KGEdge {
            r#type: "data".to_string(),
            from_node: from_node.into(),
            from_port: from_port.into(),
            to_node: to_node.into(),
            to_port: to_port.into(),
        }
    }
}

// ---------------------------------------------------------------------------
// KGNode
// ---------------------------------------------------------------------------

/// A node in the KirGraph.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct KGNode {
    pub id: String,
    pub r#type: String,
    pub name: String,
    #[serde(default)]
    pub data_inputs: Vec<KGPort>,
    #[serde(default)]
    pub data_outputs: Vec<KGPort>,
    #[serde(default)]
    pub ctrl_inputs: Vec<String>,
    #[serde(default)]
    pub ctrl_outputs: Vec<String>,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub properties: HashMap<String, Value>,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub meta: HashMap<String, Value>,
}

// ---------------------------------------------------------------------------
// KirGraph
// ---------------------------------------------------------------------------

/// Root object of a .kirgraph file.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct KirGraph {
    #[serde(default = "default_version")]
    pub version: String,
    #[serde(default)]
    pub nodes: Vec<KGNode>,
    #[serde(default)]
    pub edges: Vec<KGEdge>,
}

fn default_version() -> String {
    "0.1.0".to_string()
}

impl Default for KirGraph {
    fn default() -> Self {
        KirGraph {
            version: "0.1.0".to_string(),
            nodes: Vec::new(),
            edges: Vec::new(),
        }
    }
}

impl KirGraph {
    /// Deserialize from a JSON string.
    pub fn from_json(s: &str) -> Result<KirGraph, serde_json::Error> {
        serde_json::from_str(s)
    }

    /// Serialize to a pretty-printed JSON string (2-space indent).
    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self)
            .expect("KirGraph serialization should never fail")
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_simple_graph() -> KirGraph {
        KirGraph {
            version: "0.1.0".to_string(),
            nodes: vec![
                KGNode {
                    id: "n1".to_string(),
                    r#type: "value".to_string(),
                    name: "Value".to_string(),
                    data_inputs: vec![],
                    data_outputs: vec![KGPort {
                        port: "value".to_string(),
                        r#type: "int".to_string(),
                        default: None,
                    }],
                    ctrl_inputs: vec![],
                    ctrl_outputs: vec![],
                    properties: {
                        let mut m = HashMap::new();
                        m.insert("value".to_string(), Value::Int(42));
                        m
                    },
                    meta: HashMap::new(),
                },
                KGNode {
                    id: "n2".to_string(),
                    r#type: "print".to_string(),
                    name: "Print".to_string(),
                    data_inputs: vec![KGPort {
                        port: "x".to_string(),
                        r#type: "any".to_string(),
                        default: None,
                    }],
                    data_outputs: vec![],
                    ctrl_inputs: vec![],
                    ctrl_outputs: vec![],
                    properties: HashMap::new(),
                    meta: HashMap::new(),
                },
            ],
            edges: vec![KGEdge::data("n1", "value", "n2", "x")],
        }
    }

    #[test]
    fn test_json_roundtrip() {
        let g = make_simple_graph();
        let json = g.to_json();
        let g2 = KirGraph::from_json(&json).expect("roundtrip parse failed");
        assert_eq!(g, g2);
    }

    #[test]
    fn test_edge_nested_from_to_format() {
        let g = make_simple_graph();
        let json = g.to_json();
        let v: serde_json::Value = serde_json::from_str(&json).unwrap();
        let edge = &v["edges"][0];
        // Must use nested objects
        assert!(edge.get("from").is_some(), "edge must have nested 'from' object");
        assert!(edge.get("to").is_some(), "edge must have nested 'to' object");
        assert_eq!(edge["from"]["node"], "n1");
        assert_eq!(edge["from"]["port"], "value");
        assert_eq!(edge["to"]["node"], "n2");
        assert_eq!(edge["to"]["port"], "x");
        // Must NOT expose flat fields
        assert!(edge.get("from_node").is_none());
        assert!(edge.get("to_node").is_none());
    }

    #[test]
    fn test_port_default_omitted_when_none() {
        let g = make_simple_graph();
        let json = g.to_json();
        let v: serde_json::Value = serde_json::from_str(&json).unwrap();
        let out_port = &v["nodes"][0]["data_outputs"][0];
        assert!(out_port.get("default").is_none(), "default must be absent when None");
    }

    #[test]
    fn test_port_with_default_roundtrip() {
        let port = KGPort::with_default("x", Value::Int(0));
        let json = serde_json::to_string(&port).unwrap();
        let v: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["default"], 0);
        let port2: KGPort = serde_json::from_str(&json).unwrap();
        assert_eq!(port, port2);
    }

    #[test]
    fn test_properties_meta_omitted_when_empty() {
        let g = make_simple_graph();
        let json = g.to_json();
        let v: serde_json::Value = serde_json::from_str(&json).unwrap();
        // n2 has empty properties and meta — neither should appear
        let n2 = &v["nodes"][1];
        assert!(n2.get("properties").is_none());
        assert!(n2.get("meta").is_none());
    }

    #[test]
    fn test_from_json_minimal_defaults() {
        let json = r#"{"nodes":[],"edges":[]}"#;
        let g = KirGraph::from_json(json).unwrap();
        assert_eq!(g.version, "0.1.0");
        assert!(g.nodes.is_empty());
        assert!(g.edges.is_empty());
    }

    #[test]
    fn test_ctrl_edge_roundtrip() {
        let mut g = KirGraph::default();
        g.nodes.push(KGNode {
            id: "a".to_string(),
            r#type: "branch".to_string(),
            name: "Branch".to_string(),
            data_inputs: vec![KGPort::with_type("condition", "bool")],
            data_outputs: vec![],
            ctrl_inputs: vec!["in".to_string()],
            ctrl_outputs: vec!["true".to_string(), "false".to_string()],
            properties: HashMap::new(),
            meta: HashMap::new(),
        });
        g.edges.push(KGEdge::control("a", "true", "b", "in"));
        let json = g.to_json();
        let g2 = KirGraph::from_json(&json).unwrap();
        assert_eq!(g.edges[0].r#type, g2.edges[0].r#type);
        assert_eq!(g.edges[0].from_node, g2.edges[0].from_node);
        assert_eq!(g.edges[0].from_port, g2.edges[0].from_port);
        assert_eq!(g.edges[0].to_node, g2.edges[0].to_node);
        assert_eq!(g.edges[0].to_port, g2.edges[0].to_port);
    }
}
