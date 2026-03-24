from typing import Any

from kohakunode.ast.nodes import (
    Assignment,
    Branch,
    DataflowBlock,
    FuncCall,
    Identifier,
    Jump,
    KeywordArg,
    LabelRef,
    Literal,
    MetaAnnotation,
    ModeDecl,
    Namespace,
    Parallel,
    Parameter,
    Program,
    SubgraphDef,
    Switch,
    Wildcard,
)


def _iter_child_nodes(node: Any) -> list[Any]:
    """Return all immediate ASTNode children of *node*.

    Inspection order:
    1. Every attribute whose value is an ASTNode instance.
    2. Every attribute whose value is a list whose elements include ASTNode
       instances (only the ASTNode elements are yielded; plain values are
       skipped so mixed lists stay safe).

    The function deliberately avoids importing the base ASTNode class at
    runtime to stay decoupled — it uses duck-typing instead: any object that
    has a ``__dict__`` and is not a primitive (str/int/float/bool/bytes) is
    treated as a potential node.  Lists are flattened one level deep.
    """
    children: list[Any] = []
    obj_dict = getattr(node, "__dict__", {})
    for value in obj_dict.values():
        if _is_ast_node(value):
            children.append(value)
        elif isinstance(value, list):
            for item in value:
                if _is_ast_node(item):
                    children.append(item)
    return children


def _is_ast_node(obj: Any) -> bool:
    """Return True when *obj* looks like an AST node (has a ``__dict__`` and
    is not a plain Python scalar or string)."""
    if obj is None or isinstance(obj, (bool, int, float, str, bytes)):
        return False
    return hasattr(obj, "__dict__")


class ASTVisitor:
    """Read-only AST visitor using the *visit_ClassName* dispatch pattern.

    Subclass this and override ``visit_<NodeType>`` methods for the node types
    you care about.  Call ``self.visit(node)`` to start traversal.

    The default ``generic_visit`` does nothing; override it to add behaviour
    that applies to every unhandled node type.

    Use ``visit_children`` to recurse into child nodes from inside a
    ``visit_X`` override.
    """

    def visit(self, node: Any) -> None:
        """Dispatch *node* to ``visit_<ClassName>`` or ``generic_visit``."""
        method_name = f"visit_{type(node).__name__}"
        visitor = getattr(self, method_name, self.generic_visit)
        visitor(node)

    def generic_visit(self, node: Any) -> None:
        """Fallback called when no ``visit_<ClassName>`` method exists.

        Does nothing by default.  Override to add universal behaviour, or call
        ``self.visit_children(node)`` here to make traversal automatic for all
        unhandled nodes.
        """

    def visit_children(self, node: Any) -> None:
        """Visit every direct child node of *node*."""
        for child in _iter_child_nodes(node):
            self.visit(child)

    # ------------------------------------------------------------------
    # Concrete visit stubs — override in subclasses as needed.
    # ------------------------------------------------------------------

    def visit_Program(self, node: Program) -> None:
        self.visit_children(node)

    def visit_Assignment(self, node: Assignment) -> None:
        self.visit_children(node)

    def visit_FuncCall(self, node: FuncCall) -> None:
        self.visit_children(node)

    def visit_Namespace(self, node: Namespace) -> None:
        self.visit_children(node)

    def visit_SubgraphDef(self, node: SubgraphDef) -> None:
        self.visit_children(node)

    def visit_DataflowBlock(self, node: DataflowBlock) -> None:
        self.visit_children(node)

    def visit_ModeDecl(self, node: ModeDecl) -> None:
        self.visit_children(node)

    def visit_Identifier(self, node: Identifier) -> None:
        pass

    def visit_Literal(self, node: Literal) -> None:
        pass

    def visit_KeywordArg(self, node: KeywordArg) -> None:
        self.visit_children(node)

    def visit_Wildcard(self, node: Wildcard) -> None:
        pass

    def visit_MetaAnnotation(self, node: MetaAnnotation) -> None:
        self.visit_children(node)

    def visit_Parameter(self, node: Parameter) -> None:
        self.visit_children(node)

    def visit_LabelRef(self, node: LabelRef) -> None:
        pass

    def visit_Branch(self, node: Branch) -> None:
        self.visit_children(node)

    def visit_Switch(self, node: Switch) -> None:
        self.visit_children(node)

    def visit_Jump(self, node: Jump) -> None:
        self.visit_children(node)

    def visit_Parallel(self, node: Parallel) -> None:
        self.visit_children(node)


class ASTTransformer:
    """AST transformer using the *visit_ClassName* dispatch pattern.

    Each ``visit_<NodeType>`` method receives a node and **must return** a
    node — either the same object (possibly mutated in-place) or a brand-new
    replacement node.

    The default ``generic_visit`` recursively transforms all children and
    returns the (possibly child-modified) node unchanged at the current level.
    Override ``visit_<NodeType>`` to intercept and replace specific node
    types.

    Call ``self.visit(node)`` to start the transformation; it returns the
    (potentially replaced) root node.
    """

    def visit(self, node: Any) -> Any:
        """Dispatch *node* to ``visit_<ClassName>`` or ``generic_visit``."""
        method_name = f"visit_{type(node).__name__}"
        transformer = getattr(self, method_name, self.generic_visit)
        return transformer(node)

    def generic_visit(self, node: Any) -> Any:
        """Recursively transform all child nodes of *node* in-place.

        For each attribute of *node*:
        - If the value is an AST node, replace it with ``self.visit(value)``.
        - If the value is a list, replace each AST-node element with its
          transformed counterpart (non-node elements are left untouched).

        Returns *node* after all children have been updated.
        """
        obj_dict = getattr(node, "__dict__", {})
        for attr, value in obj_dict.items():
            if _is_ast_node(value):
                setattr(node, attr, self.visit(value))
            elif isinstance(value, list):
                new_list = []
                for item in value:
                    if _is_ast_node(item):
                        new_list.append(self.visit(item))
                    else:
                        new_list.append(item)
                setattr(node, attr, new_list)
        return node

    # ------------------------------------------------------------------
    # Concrete transform stubs — override in subclasses as needed.
    # Each default implementation delegates to generic_visit so child
    # transformation still happens unless the override takes full control.
    # ------------------------------------------------------------------

    def visit_Program(self, node: Program) -> Program:
        return self.generic_visit(node)

    def visit_Assignment(self, node: Assignment) -> Assignment:
        return self.generic_visit(node)

    def visit_FuncCall(self, node: FuncCall) -> FuncCall:
        return self.generic_visit(node)

    def visit_Namespace(self, node: Namespace) -> Namespace:
        return self.generic_visit(node)

    def visit_SubgraphDef(self, node: SubgraphDef) -> SubgraphDef:
        return self.generic_visit(node)

    def visit_DataflowBlock(self, node: DataflowBlock) -> DataflowBlock:
        return self.generic_visit(node)

    def visit_ModeDecl(self, node: ModeDecl) -> ModeDecl:
        return self.generic_visit(node)

    def visit_Identifier(self, node: Identifier) -> Identifier:
        return node

    def visit_Literal(self, node: Literal) -> Literal:
        return node

    def visit_KeywordArg(self, node: KeywordArg) -> KeywordArg:
        return self.generic_visit(node)

    def visit_Wildcard(self, node: Wildcard) -> Wildcard:
        return node

    def visit_MetaAnnotation(self, node: MetaAnnotation) -> MetaAnnotation:
        return self.generic_visit(node)

    def visit_Parameter(self, node: Parameter) -> Parameter:
        return self.generic_visit(node)

    def visit_LabelRef(self, node: LabelRef) -> LabelRef:
        return node

    def visit_Branch(self, node: Branch) -> Branch:
        return self.generic_visit(node)

    def visit_Switch(self, node: Switch) -> Switch:
        return self.generic_visit(node)

    def visit_Jump(self, node: Jump) -> Jump:
        return self.generic_visit(node)

    def visit_Parallel(self, node: Parallel) -> Parallel:
        return self.generic_visit(node)

    # ------------------------------------------------------------------
    # Convenience alias so transformer instances can also call
    # visit_children explicitly (mirrors ASTVisitor API).
    # ------------------------------------------------------------------

    def visit_children(self, node: Any) -> None:
        """Transform each child node in-place (return values discarded).

        Useful inside a ``visit_X`` override when you want to recurse without
        replacing the current node.  If you need the returned nodes, call
        ``self.generic_visit(node)`` instead and use its return value.
        """
        obj_dict = getattr(node, "__dict__", {})
        for attr, value in obj_dict.items():
            if _is_ast_node(value):
                setattr(node, attr, self.visit(value))
            elif isinstance(value, list):
                new_list = []
                for item in value:
                    if _is_ast_node(item):
                        new_list.append(self.visit(item))
                    else:
                        new_list.append(item)
                setattr(node, attr, new_list)
