from __future__ import annotations

from .cst import (
    ArrayNode,
    Document,
    LiteralNode,
    MemberNode,
    NumberNode,
    ObjectNode,
    StringNode,
    ValueNode,
)
from .lexer import Lexer
from .parser import Parser


def sort_jsonc(source: str, filename: str | None = None) -> str:
    tokens = Lexer(source, filename).tokenize()
    document = Parser(tokens, filename, source).parse_document()
    return render_document(source, document)


def render_document(source: str, document: Document) -> str:
    return (
        source[: document.value.start]
        + render_value(source, document.value)
        + source[document.value.end : document.eof.start]
    )


def render_value(source: str, node: ValueNode) -> str:
    if isinstance(node, ObjectNode):
        return render_object(source, node)
    if isinstance(node, ArrayNode):
        return render_array(source, node)
    if isinstance(node, (StringNode, NumberNode, LiteralNode)):
        return source[node.start : node.end]
    raise TypeError(f"unsupported node: {node!r}")


def render_object(source: str, node: ObjectNode) -> str:
    if not node.members:
        return source[node.start : node.end]

    member_parts = [_render_member_parts(source, member) for member in node.members]
    sorted_indexes = sorted(
        range(len(node.members)),
        key=lambda i: (node.members[i].sort_key, node.members[i].index),
    )

    first = node.members[0]
    body_start = first.leading_start
    body_end = node.rbrace.start
    prefix = source[node.start : body_start]
    suffix = source[body_end : node.end]

    slot_starts = [member.leading_start for member in node.members]
    separator_tokens = [*node.separators]
    if node.trailing_comma is not None:
        separator_tokens.append(node.trailing_comma)

    slots: list[tuple[str, str]] = []
    for i in range(len(node.members) - 1):
        separator = separator_tokens[i]
        gap_after_separator = source[separator.end : slot_starts[i + 1]]
        carried_comment, remaining_gap = _split_same_line_comment_after_separator(
            gap_after_separator
        )
        core, inline = member_parts[i]
        member_parts[i] = (core, inline + carried_comment)
        slots.append(
            (source[node.members[i].trailing_end : separator.end], remaining_gap)
        )

    # Preserve any non-comma layout between the final member and the closing
    # brace. If there was a trailing comma, drop only the comma token.
    if node.trailing_comma is not None:
        final_suffix = source[node.members[-1].trailing_end : node.trailing_comma.start]
        final_suffix += source[node.trailing_comma.end : body_end]
    else:
        final_suffix = source[node.members[-1].trailing_end : body_end]

    body_parts: list[str] = []
    for output_index, member_index in enumerate(sorted_indexes):
        core, inline = member_parts[member_index]
        body_parts.append(core)
        if output_index < len(slots):
            separator_text, gap_after_separator = slots[output_index]
            body_parts.append(separator_text)
            body_parts.append(inline)
            body_parts.append(gap_after_separator)
        else:
            body_parts.append(inline)
    body_parts.append(final_suffix)

    return prefix + "".join(body_parts) + suffix


def _render_member_parts(source: str, member: MemberNode) -> tuple[str, str]:
    core = (
        source[member.leading_start : member.start]
        + source[member.start : member.value.start]
        + render_value(source, member.value)
    )
    inline = source[member.value.end : member.trailing_end]
    return core, inline


def _split_same_line_comment_after_separator(text: str) -> tuple[str, str]:
    index = 0
    while index < len(text) and text[index] in " \t":
        index += 1
    if index >= len(text) or text[index] in "\r\n":
        return "", text

    if text.startswith("//", index):
        newline_index = len(text)
        for marker in ("\r", "\n"):
            found = text.find(marker, index)
            if found != -1:
                newline_index = min(newline_index, found)
        return text[:newline_index], text[newline_index:]

    if text.startswith("/*", index):
        end = text.find("*/", index + 2)
        if end != -1:
            end += 2
            return text[:end], text[end:]

    return "", text


def render_array(source: str, node: ArrayNode) -> str:
    if not node.values:
        return source[node.start : node.end]

    rendered_values = [render_value(source, value) for value in node.values]
    first = node.values[0]
    body_start = first.start
    body_end = node.rbracket.start
    prefix = source[node.start : body_start]
    suffix = source[body_end : node.end]

    separator_tokens = [*node.separators]
    if node.trailing_comma is not None:
        separator_tokens.append(node.trailing_comma)

    parts: list[str] = []
    for i, value_text in enumerate(rendered_values):
        parts.append(value_text)
        if i < len(node.values) - 1:
            separator = separator_tokens[i]
            parts.append(source[node.values[i].end : separator.end])
            parts.append(source[separator.end : node.values[i + 1].start])

    if node.trailing_comma is not None:
        parts.append(source[node.values[-1].end : node.trailing_comma.start])
        parts.append(source[node.trailing_comma.end : body_end])
    else:
        parts.append(source[node.values[-1].end : body_end])

    return prefix + "".join(parts) + suffix
