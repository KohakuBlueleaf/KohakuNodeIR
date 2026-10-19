//! `kir.std`, the standard node library, and the internal `kir.` nodes `expand_each` uses.

use std::sync::OnceLock;

use crate::sig::model::{Library, Port, Signature};
use crate::syntax::ast::TypeExpr;

fn sig(name: &str, inputs: &[(&str, &str)], outputs: &[(&str, &str)]) -> Signature {
    let ports = |list: &[(&str, &str)]| {
        list.iter().map(|(n, t)| Port::new(*n, if *t == "_" { TypeExpr::Any } else { TypeExpr::name(t) })).collect()
    };
    Signature::new(name, ports(inputs), ports(outputs))
}

fn library(name: &str, sigs: Vec<Signature>) -> Library {
    let mut lib = Library::new(name);
    for s in sigs {
        lib.add_signature(s).expect("distinct built-in names");
    }
    lib
}

/// The `kir.std` library.
pub fn std_library() -> &'static Library {
    static STD: OnceLock<Library> = OnceLock::new();
    STD.get_or_init(|| {
        let ab = [("a", "_"), ("b", "_")];
        let any = [("result", "_")];
        let boolean = [("result", "bool")];
        let mut print_value = sig("print_value", &[("value", "_")], &[]);
        print_value.ordered = true;
        library(
            "kir.std",
            vec![
                sig("add", &ab, &any),
                sig("sub", &ab, &any),
                sig("mul", &ab, &any),
                sig("div", &ab, &any),
                sig("floordiv", &ab, &any),
                sig("mod", &ab, &any),
                sig("neg", &[("a", "_")], &any),
                sig("less", &ab, &boolean),
                sig("less_equal", &ab, &boolean),
                sig("greater", &ab, &boolean),
                sig("greater_equal", &ab, &boolean),
                sig("equal", &ab, &boolean),
                sig("not_equal", &ab, &boolean),
                sig("not", &[("a", "_")], &boolean),
                sig("and", &ab, &boolean),
                sig("or", &ab, &boolean),
                sig("len", &[("items", "_")], &[("result", "int")]),
                sig("item_at", &[("items", "_"), ("index", "int")], &any),
                sig("append", &[("items", "list"), ("item", "_")], &[("result", "list")]),
                sig("concat", &ab, &any),
                sig("range", &[("n", "int")], &[("result", "list")]),
                sig("to_str", &[("value", "_")], &[("result", "str")]),
                sig("to_int", &[("value", "_")], &[("result", "int")]),
                sig("to_float", &[("value", "_")], &[("result", "float")]),
                sig("identity", &[("value", "_")], &any),
                print_value,
            ],
        )
    })
}

/// The internal `kir.` nodes of the `expand_each` pass.
pub fn internal_library() -> &'static Library {
    static INTERNAL: OnceLock<Library> = OnceLock::new();
    INTERNAL.get_or_init(|| {
        library(
            "kir",
            vec![
                sig("kir.to_list", &[("items", "_")], &[("result", "list")]),
                sig("kir.item_at", &[("items", "list"), ("index", "int")], &[("item", "_"), ("more", "_")]),
                sig("kir.next_index", &[("index", "int")], &[("result", "int")]),
            ],
        )
    })
}
