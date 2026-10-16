"""Local syntax navigation. Names and framework registrations never prove reachability."""

from functools import lru_cache

PARSER_LANGUAGES = {
    "python",
    "javascript",
    "typescript",
    "java",
    "go",
    "csharp",
    "php",
    "ruby",
    "rust",
    "kotlin",
    "swift",
    "c",
    "cpp",
}
DEFINITIONS = {
    "function_definition",
    "function_declaration",
    "method_declaration",
    "method_definition",
    "constructor_declaration",
    "class_declaration",
    "class_definition",
    "interface_declaration",
    "struct_item",
    "enum_item",
    "function_item",
    "method",
    "singleton_method",
    "class",
    "struct_specifier",
    "namespace_definition",
    "object_declaration",
}
IMPORTS = {
    "import_statement",
    "import_declaration",
    "import_from_statement",
    "using_directive",
    "use_declaration",
    "use_as_clause",
    "preproc_include",
    "package_clause",
    "import_header",
}
CALLS = {
    "call",
    "call_expression",
    "method_invocation",
    "invocation_expression",
    "function_call_expression",
    "member_call_expression",
    "scoped_call_expression",
}


@lru_cache(maxsize=20)
def _language(language):
    # Cache grammars, not mutable Parser instances (indexes may be built concurrently).
    from tree_sitter_language_pack import get_language

    return get_language(language)


def parse_source(text, language):
    from tree_sitter import Parser

    return Parser(_language(language)).parse(text.encode("utf-8"))


def walk(node):
    stack = [node]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(reversed(item.named_children))


def node_text(node):
    return node.text.decode("utf-8", errors="replace") if node else ""


def declaration_name(node):
    name = node.child_by_field_name("name")
    if name:
        return node_text(name)
    # C/C++ function pointers and declarators can be nested.
    declarator = node.child_by_field_name("declarator")
    while declarator:
        if declarator.type in {"identifier", "field_identifier", "qualified_identifier"}:
            return node_text(declarator)
        declarator = declarator.child_by_field_name("declarator")
    # Kotlin and Swift expose the name as a direct identifier, without a name field.
    return next(
        (
            node_text(c)
            for c in node.named_children
            if c.type in {"identifier", "simple_identifier", "type_identifier"}
        ),
        "",
    )


def code_only(text, tree):
    """Keep offsets/newlines; hide comments and string literals from registration matching."""
    masked = bytearray(text.encode("utf-8"))
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if "comment" in node.type or node.type in {
            "string",
            "string_literal",
            "interpreted_string_literal",
            "raw_string_literal",
            "template_string",
            "encapsed_string",
            "heredoc_body",
            "character_literal",
            "verbatim_string_literal",
            "raw_string",
            "string_value",
            "line_string_literal",
            "multi_line_string_literal",
        }:
            # Interpolated expressions remain discoverable through syntax navigation, not
            # registration heuristics. Never discover a route from documentation/examples.
            for offset in range(node.start_byte, node.end_byte):
                if masked[offset] not in (10, 13):
                    masked[offset] = 32
        else:
            stack.extend(node.named_children)
    return masked.decode("utf-8", errors="replace")
