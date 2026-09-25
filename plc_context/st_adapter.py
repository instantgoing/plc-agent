"""Tree-sitter ST adapter. This extracts only facts supported by known nodes."""

from __future__ import annotations

from tree_sitter import Language, Parser
import tree_sitter_iec61131_3_st

from .model import (
    DataType, Diagnostic, PLCSourceFile, POU, ParsedSource, SourceLocation,
    Task, UsageCandidate, Variable,
)


_LANGUAGE = Language(tree_sitter_iec61131_3_st.language())
_POU_KINDS = {
    "program_declaration": "program",
    "function_block_declaration": "function_block",
    "function_declaration": "function",
}
_VAR_SCOPES = {
    "var_block": "local",
    "var_input": "input",
    "var_output": "output",
    "var_in_out": "inout",
    "var_temp": "temporary",
    "var_global": "global",
    "var_external": "external",
}
_UNSUPPORTED = {
    "interface_declaration", "namespace_declaration", "method_declaration",
    "property_declaration", "var_access", "var_config",
}


def _text(source: bytes, node) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _location(file: str, node) -> SourceLocation:
    return SourceLocation(file, node.start_point.row + 1, node.start_point.column + 1,
                          node.end_point.row + 1, node.end_point.column + 1)


def _walk(node):
    yield node
    for child in node.named_children:
        yield from _walk(child)


def _var_block(source: bytes, file: str, block, owner: str | None) -> list[Variable]:
    scope = _VAR_SCOPES[block.type]
    constant = any(child.type == "var_qualifier" and _text(source, child).upper() == "CONSTANT"
                   for child in _walk(block))
    result: list[Variable] = []
    for declaration in block.named_children:
        if declaration.type != "variable_declaration" or declaration.has_error:
            continue
        type_node = declaration.child_by_field_name("type")
        if type_node is None:
            continue
        type_name = _text(source, type_node).strip()
        address_node = declaration.child_by_field_name("address")
        address = _text(source, address_node).upper() if address_node else None
        initial_node = declaration.child_by_field_name("initial_value")
        initial = _text(source, initial_node).strip() if initial_node else None
        names = [child for child in declaration.named_children
                 if child.type == "identifier" and child.start_byte < type_node.start_byte]
        for name_node in names:
            result.append(Variable(
                _text(source, name_node), type_name,
                "constant" if constant and scope == "local" else scope,
                owner, address, initial, _location(file, name_node),
                constant=constant, located=address is not None,
            ))
    return result


def _body_usages(source: bytes, file: str, body_nodes: list, owner: str) -> list[UsageCandidate]:
    result: list[UsageCandidate] = []
    seen: set[tuple[int, int, bool]] = set()
    for body in body_nodes:
        for node in _walk(body):
            if node.type == "member_access_expression":
                object_node = node.child_by_field_name("object")
                member_node = node.child_by_field_name("member")
                if object_node and object_node.type == "identifier" and member_node:
                    key = (member_node.start_byte, member_node.end_byte, False)
                    if key not in seen:
                        result.append(UsageCandidate(_text(source, member_node), owner, False,
                                                     _location(file, member_node),
                                                     object=_text(source, object_node)))
                        seen.add(key)
            if node.type == "call_expression":
                function = node.child_by_field_name("function")
                if function and function.type == "identifier":
                    key = (function.start_byte, function.end_byte, True)
                    if key not in seen:
                        result.append(UsageCandidate(_text(source, function), owner, True,
                                                     _location(file, function)))
                        seen.add(key)
            if node.type != "identifier":
                continue
            parent = node.parent
            if parent and parent.type == "named_argument" and parent.child_by_field_name("name") == node:
                continue
            key = (node.start_byte, node.end_byte, False)
            if key not in seen:
                result.append(UsageCandidate(_text(source, node), owner, False,
                                             _location(file, node)))
                seen.add(key)
    return result


def parse_st(source: bytes, file: str) -> ParsedSource:
    """Parse one file; syntax errors stay local to this file's result."""
    try:
        source.decode("utf-8")
    except UnicodeDecodeError as exc:
        diagnostic = Diagnostic(file, 1, 1, f"ST source is not UTF-8: {exc}")
        return ParsedSource(PLCSourceFile(file, False, False, (diagnostic,)))
    tree = Parser(_LANGUAGE).parse(source)
    root = tree.root_node
    diagnostics: list[Diagnostic] = []
    unsupported: list[str] = []
    for node in _walk(root):
        if node.type == "ERROR" or node.is_missing:
            diagnostics.append(Diagnostic(file, node.start_point.row + 1,
                                          node.start_point.column + 1,
                                          "ST syntax cannot be indexed reliably here"))
            unsupported.append(f"unrecognized or incomplete syntax at line {node.start_point.row + 1}")
        elif node.type in _UNSUPPORTED:
            unsupported.append(f"{node.type} at line {node.start_point.row + 1}")
    pous: list[POU] = []
    globals_: list[Variable] = []
    data_types: list[DataType] = []
    tasks: list[Task] = []
    usages: list[UsageCandidate] = []
    for node in _walk(root):
        if node.type in _POU_KINDS:
            if node.has_error:
                continue
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = _text(source, name_node)
            variables: list[Variable] = []
            body_nodes: list = []
            for child in node.named_children:
                if child.type in _VAR_SCOPES:
                    target = _var_block(source, file, child, name)
                    if child.type == "var_global":
                        globals_.extend(target)
                    else:
                        variables.extend(target)
                elif child.type.endswith("_statement") or child.type == "call_expression":
                    body_nodes.append(child)
            return_node = node.child_by_field_name("return_type")
            pous.append(POU(name, _POU_KINDS[node.type], _location(file, node),
                            tuple(variables), _text(source, return_node) if return_node else None))
            usages.extend(_body_usages(source, file, body_nodes, name))
        elif node.type == "var_global" and not any(parent.type in _POU_KINDS for parent in _parents(node)):
            if not node.has_error:
                globals_.extend(_var_block(source, file, node, None))
        elif node.type == "type_definition" and not node.has_error:
            name_node = node.child_by_field_name("name")
            if name_node:
                data_types.append(DataType(_text(source, name_node), _text(source, node),
                                           _location(file, name_node)))
        elif node.type == "task_declaration" and not node.has_error:
            name_node = node.child_by_field_name("name")
            if name_node:
                parameters = {(_text(source, item.child_by_field_name("name")).upper()
                               if item.child_by_field_name("name") else ""):
                              (_text(source, item.child_by_field_name("value"))
                               if item.child_by_field_name("value") else "")
                              for item in node.named_children if item.type == "task_parameter"}
                tasks.append(Task(_text(source, name_node), parameters.get("INTERVAL"),
                                  parameters.get("PRIORITY"), _location(file, name_node)))
    if root.has_error and not diagnostics:
        diagnostics.append(Diagnostic(file, 1, 1, "ST source has an unrecognized or incomplete construct"))
    complete = not root.has_error and not unsupported
    source_file = PLCSourceFile(file, complete, complete, tuple(diagnostics),
                                tuple(dict.fromkeys(unsupported)))
    return ParsedSource(source_file, tuple(pous), tuple(globals_),
                        tuple(data_types), tuple(tasks), tuple(usages))


def _parents(node):
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent
