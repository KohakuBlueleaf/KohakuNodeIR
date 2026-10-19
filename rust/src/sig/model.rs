//! Node signatures and libraries.

use indexmap::IndexMap;

use crate::errors::{KirError, Result};
use crate::syntax::ast::TypeExpr;
use crate::syntax::value::Value;

#[derive(Clone, Debug)]
pub struct Port {
    pub name: String,
    pub ty: TypeExpr,
    /// None when the input must be given.
    pub default: Option<Value>,
}

impl Port {
    pub fn new(name: impl Into<String>, ty: TypeExpr) -> Port {
        Port { name: name.into(), ty, default: None }
    }

    pub fn required(&self) -> bool {
        self.default.is_none()
    }
}

#[derive(Clone, Debug)]
pub struct Signature {
    pub name: String,
    pub inputs: Vec<Port>,
    pub outputs: Vec<Port>,
    pub mutates: Vec<String>,
    pub ordered: bool,
    pub doc: String,
}

impl Signature {
    pub fn new(name: impl Into<String>, inputs: Vec<Port>, outputs: Vec<Port>) -> Signature {
        Signature { name: name.into(), inputs, outputs, mutates: vec![], ordered: false, doc: String::new() }
    }

    pub fn input(&self, name: &str) -> Option<&Port> {
        self.inputs.iter().find(|p| p.name == name)
    }
}

/// Named signatures.
#[derive(Clone, Debug)]
pub struct Library {
    pub name: String,
    pub signatures: IndexMap<String, Signature>,
}

impl Library {
    pub fn new(name: impl Into<String>) -> Library {
        Library { name: name.into(), signatures: IndexMap::new() }
    }

    pub fn contains(&self, node: &str) -> bool {
        self.signatures.contains_key(node)
    }

    pub fn add_signature(&mut self, sig: Signature) -> Result<()> {
        if self.signatures.contains_key(&sig.name) {
            return Err(KirError::Value(format!(
                "library {} already has a node {}",
                crate::util::pyfmt::str_repr(&self.name),
                crate::util::pyfmt::str_repr(&sig.name)
            )));
        }
        self.signatures.insert(sig.name.clone(), sig);
        Ok(())
    }
}
