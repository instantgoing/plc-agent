"""Conservative Tree-sitter AST -> read-only Ladder IR. Never a source compiler."""
from __future__ import annotations

import hashlib
from tree_sitter import Parser
from plc_context.st_adapter import _LANGUAGE, _text, _location, parse_st


class Unsupported(ValueError):
    pass


def ladder_ir(source: bytes, file: str) -> dict:
    parsed = parse_st(source, file)
    root = Parser(_LANGUAGE).parse(source).root_node
    rungs, unsupported = [], []
    declarations = {p.name.casefold(): p for p in parsed.pous}
    ast = { _text(source, n.child_by_field_name("name")).casefold(): n
            for n in root.named_children if n.type in {"program_declaration", "function_block_declaration"}
            and n.child_by_field_name("name")}
    globals_ = {v.name.casefold(): v for v in parsed.globals}

    def location(node):
        return vars(_location(file, node))

    def negate(child, source_location):
        # De Morgan's law is required: NOT(A AND B) cannot be drawn as an
        # ordinary series with a vague "NOT" annotation.
        if child["kind"] in {"series", "parallel"}:
            return {**child, "kind": "parallel" if child["kind"] == "series" else "series",
                    "children": [negate(c, source_location) for c in child["children"]]}
        if child["kind"] == "not":
            return child["child"]
        if child["kind"] == "constant":
            return {**child, "value": not child["value"]}
        if child["kind"] == "comparison":
            return {**child, "operator": {"=": "<>", "<>": "=", "<": ">=", ">": "<=", "<=": ">", ">=": "<"}[child["operator"]]}
        return {"kind": "not", "child": child, "type": "BOOL", "source": source_location}

    def expression(node, owner, variables):
        if node is None or node.has_error:
            raise Unsupported("incomplete expression")
        if node.type == "parenthesized_expression":
            return expression(node.named_children[0], owner, variables)
        if node.type in {"identifier", "member_access_expression"}:
            text = _text(source, node)
            parts = text.split(".")
            v = variables.get(parts[0].casefold()) or globals_.get(parts[0].casefold())
            if v is None:
                raise Unsupported("unresolved symbol " + text)
            scope_owner = "GVL" if v.scope == "global" else owner
            target_type = v.type.upper()
            if len(parts) > 1:
                child = declarations.get(v.type.casefold())
                if child:
                    member = next((x for x in child.variables if x.name.casefold() == parts[-1].casefold()), None)
                    target_type = member.type.upper() if member else "UNKNOWN"
                elif target_type in {"TON", "TOF"}:
                    target_type = {"q": "BOOL", "in": "BOOL", "et": "TIME", "pt": "TIME"}.get(parts[-1].casefold(), "UNKNOWN")
                else:
                    raise Unsupported("unsupported member " + text)
                scope_owner += "." + ".".join(parts[:-1])
            return {"kind": "contact", "symbol": text, "variable_id": f"{scope_owner}:{parts[-1]}".casefold(),
                    "type": target_type, "source": location(node)}
        if node.type == "boolean_literal":
            return {"kind": "constant", "value": _text(source, node).upper() == "TRUE", "type": "BOOL", "source": location(node)}
        if node.type in {"integer_literal", "real_literal"}:
            try:
                return {"kind": "constant", "value": float(_text(source, node)), "type": "REAL", "source": location(node)}
            except ValueError:
                raise Unsupported("typed or radix literal")
        if node.type == "unary_expression":
            operand = node.child_by_field_name("operand")
            op = source[node.start_byte:operand.start_byte].decode().strip().upper()
            child = expression(operand, owner, variables)
            if op != "NOT" or child["type"] != "BOOL":
                raise Unsupported("non-BOOL NOT/unary operation")
            return negate(child, location(node))
        if node.type == "binary_expression":
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            op = source[left.end_byte:right.start_byte].decode().strip().upper()
            a, b = expression(left, owner, variables), expression(right, owner, variables)
            if op in {"AND", "OR"} and a["type"] == b["type"] == "BOOL":
                return {"kind": "series" if op == "AND" else "parallel", "children": [a, b], "type": "BOOL", "source": location(node)}
            if op in {"=", "<>", "<", ">", "<=", ">="} and a["type"] in {"BOOL", "INT", "DINT", "REAL", "LREAL", "UINT", "SINT"} and b["type"] in {"BOOL", "INT", "DINT", "REAL", "LREAL", "UINT", "SINT"}:
                return {"kind": "comparison", "operator": op, "left": a, "right": b, "type": "BOOL", "source": location(node)}
            raise Unsupported("arithmetic, bitwise or unsupported expression " + op)
        raise Unsupported(node.type)

    def visit(pou, owner, stack=()):
        node = ast.get(pou.name.casefold())
        if node is None or pou.name in stack:
            return
        variables = {v.name.casefold(): v for v in pou.variables}
        for statement in node.named_children:
            if statement.type in {"identifier", "var_block", "var_input", "var_output", "var_in_out", "var_temp", "var_external", "elementary_type", "empty_statement"}:
                continue
            try:
                if statement.has_error:
                    raise Unsupported("syntax error")
                if statement.type == "assignment_statement":
                    coil = expression(statement.child_by_field_name("left"), owner, variables)
                    logic = expression(statement.child_by_field_name("right"), owner, variables)
                    if coil["type"] != "BOOL" or logic["type"] != "BOOL":
                        raise Unsupported("non-BOOL assignment")
                    coil["kind"] = "coil"
                    rungs.append({"id": f"{owner}:{statement.start_byte}", "owner": owner,
                                  "logic": logic, "output": coil, "source": location(statement)})
                elif statement.type == "invocation_statement":
                    call = statement.named_children[0]
                    function = call.child_by_field_name("function")
                    name = _text(source, function)
                    variable = variables.get(name.casefold())
                    if not variable or variable.type.upper() not in {"TON", "TOF"}:
                        raise Unsupported("FB invocation wiring")
                    args = call.child_by_field_name("arguments")
                    params = {_text(source, a.child_by_field_name("name")).upper(): a.child_by_field_name("value")
                              for a in args.named_children if a.type == "named_argument"}
                    if set(params) != {"IN", "PT"} or params["PT"].type != "time_literal":
                        raise Unsupported("timer requires IN and literal PT")
                    logic = expression(params["IN"], owner, variables)
                    if logic["type"] != "BOOL":
                        raise Unsupported("timer IN must be BOOL")
                    rungs.append({"id": f"{owner}:{statement.start_byte}", "owner": owner, "logic": logic,
                                  "output": {"kind": "timer", "timer_type": variable.type.upper(), "symbol": name,
                                             "pt": _text(source, params["PT"]), "q_id": f"{owner}.{name}:Q".casefold(),
                                             "et_id": f"{owner}.{name}:ET".casefold(), "source": location(statement)},
                                  "source": location(statement)})
                else:
                    raise Unsupported(statement.type)
            except Unsupported as exc:
                unsupported.append({**location(statement), "construct": str(exc), "owner": owner})
        # Expand FB definitions by concrete instance, never by type-name identity.
        for v in pou.variables:
            child = declarations.get(v.type.casefold())
            if child and child.kind == "function_block":
                visit(child, f"{owner}.{v.name}", (*stack, pou.name))
    for p in parsed.pous:
        if p.kind == "program":
            visit(p, p.name)
    unsupported.extend({"file": d.file, "line": d.line, "construct": d.message} for d in parsed.source_file.diagnostics)
    return {"status": "partial" if rungs and unsupported else "supported" if rungs else "unsupported",
            "source_hash": hashlib.sha256(source.decode().replace('\r\n', '\n').encode()).hexdigest(),
            "rungs": rungs, "unsupported": unsupported, "file": file,
            "semantics": "contacts and outputs are observed snapshots; scan execution is not traced"}
