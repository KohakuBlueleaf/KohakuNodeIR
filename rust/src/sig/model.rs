//! Node signatures and libraries.

use indexmap::IndexMap;

use crate::errors::{KirError, Result};
use crate::sig::records::{generated_names, record_signatures, validate_record_cycles, RecordSchema};
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
    pub records: IndexMap<String, RecordSchema>,
}

impl Library {
    pub fn new(name: impl Into<String>) -> Library {
        Library { name: name.into(), signatures: IndexMap::new(), records: IndexMap::new() }
    }

    pub fn contains(&self, node: &str) -> bool {
        self.signatures.contains_key(node)
    }

    pub fn add_signature(&mut self, mut sig: Signature) -> Result<()> {
        if self.signatures.contains_key(&sig.name) || self.records.contains_key(&sig.name) {
            return Err(KirError::Value(format!(
                "library {} already has a node or record {}",
                crate::util::pyfmt::str_repr(&self.name),
                crate::util::pyfmt::str_repr(&sig.name)
            )));
        }
        qualify_record_signature(&mut sig, &self.records);
        self.signatures.insert(sig.name.clone(), sig);
        Ok(())
    }

    /// Register a validated nominal schema and its ordinary pure make/get/with nodes.
    /// Every validation finishes before mutating the library.
    pub fn add_record(&mut self, schema: RecordSchema) -> Result<&RecordSchema> {
        let schema = schema.qualify(&self.name)?;
        let name = schema.name().to_string();
        if self.records.contains_key(&name) || self.signatures.contains_key(&name) {
            return Err(KirError::Value(format!(
                "library {} already has a node or record {}",
                crate::util::pyfmt::str_repr(&self.name),
                crate::util::pyfmt::str_repr(&name)
            )));
        }
        for generated in generated_names(&schema) {
            if self.signatures.contains_key(&generated) {
                return Err(KirError::Value(format!(
                    "record {} generated node collision: {}",
                    crate::util::pyfmt::str_repr(&name),
                    crate::util::pyfmt::str_repr(&generated)
                )));
            }
        }
        validate_record_cycles(self.records.values().chain(std::iter::once(&schema)))?;
        let signatures = record_signatures(&schema);
        self.records.insert(name.clone(), schema);
        for signature in self.signatures.values_mut() {
            qualify_record_signature(signature, &self.records);
        }
        for signature in signatures {
            self.signatures.insert(signature.name.clone(), signature);
        }
        Ok(&self.records[&name])
    }
}

/// Qualify known local record names only; unrelated host nominal types stay unchanged.
pub fn qualify_record_signature(signature: &mut Signature, records: &IndexMap<String, RecordSchema>) {
    fn qualify(ty: &mut TypeExpr, records: &IndexMap<String, RecordSchema>) {
        match ty {
            TypeExpr::Name(name) => {
                if let Some(schema) = records.get(name) {
                    *name = schema.schema_id().into();
                }
            }
            TypeExpr::Optional(inner) => qualify(inner, records),
            TypeExpr::Generic(_, parts) | TypeExpr::Union(parts) => {
                for part in parts {
                    qualify(part, records);
                }
            }
            _ => {}
        }
    }
    for port in signature.inputs.iter_mut().chain(&mut signature.outputs) {
        qualify(&mut port.ty, records);
    }
}
