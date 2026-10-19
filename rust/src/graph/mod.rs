//! The graph view (`.kirgraph`): conversion from and to programs.

pub mod from_graph;
pub mod to_graph;

pub use from_graph::from_graph;
pub use to_graph::{to_graph, DataStyle};
