from __future__ import annotations

import json

from .cst import (
    ArrayNode,
    Document,
    LiteralNode,
    MemberNode,
    NumberNode,
    ObjectNode,
    StringNode,
    Token,
    TokenKind,
    TRIVIA_KINDS,
    ValueNode,
)
from .errors import JsoncSyntaxError


class Parser:
    def __init__(
        self, tokens: list[Token], filename: str | None = None, source: str = ""
    ):
        self.tokens = tokens
        self.filename = filename
        self.source = source
        self.pos = 0

    def parse_document(self) -> Document:
        leading_trivia = self._consume_trivia()
        value = self._parse_value()
        trailing_trivia = self._consume_trivia()
        eof = self._expect(TokenKind.EOF, "expected end of file")
        return Document(leading_trivia, value, trailing_trivia, eof)

    def _parse_value(self) -> ValueNode:
        self._consume_trivia()
        token = self._peek()
        if token.kind == TokenKind.LBRACE:
            return self._parse_object()
        if token.kind == TokenKind.LBRACKET:
            return self._parse_array()
        if token.kind == TokenKind.STRING:
            return self._parse_string()
        if token.kind == TokenKind.NUMBER:
            return NumberNode(self._advance())
        if token.kind in {TokenKind.TRUE, TokenKind.FALSE, TokenKind.NULL}:
            return LiteralNode(self._advance())
        raise self._error(token, "expected JSONC value")

    def _parse_object(self) -> ObjectNode:
        lbrace = self._expect(TokenKind.LBRACE, "expected '{'")
        members: list[MemberNode] = []
        separators: list[Token] = []
        trailing_comma: Token | None = None

        mark = self.pos
        self._consume_trivia()
        if self._peek().kind == TokenKind.RBRACE:
            return ObjectNode(lbrace, members, separators, None, self._advance())
        self.pos = mark

        while True:
            member = self._parse_member(len(members))
            members.append(member)
            trailing_trivia = self._consume_trivia()
            member.trailing_end = self._same_line_trailing_end(
                trailing_trivia, member.value.end
            )

            if self._peek().kind == TokenKind.COMMA:
                comma = self._advance()
                mark = self.pos
                self._consume_trivia()
                if self._peek().kind == TokenKind.RBRACE:
                    trailing_comma = comma
                    rbrace = self._advance()
                    return ObjectNode(
                        lbrace, members, separators, trailing_comma, rbrace
                    )
                self.pos = mark
                separators.append(comma)
                continue

            if self._peek().kind == TokenKind.RBRACE:
                return ObjectNode(
                    lbrace, members, separators, trailing_comma, self._advance()
                )

            raise self._error(self._peek(), "expected ',' or '}' after object member")

    def _parse_member(self, index: int) -> MemberNode:
        leading_trivia = self._consume_trivia()
        key = self._parse_string()
        self._consume_trivia()
        colon = self._expect(TokenKind.COLON, "expected ':' after object key")
        value = self._parse_value()
        leading_start = self._carried_leading_start(leading_trivia, key.start)
        return MemberNode(key, colon, value, index, leading_start, value.end)

    def _parse_array(self) -> ArrayNode:
        lbracket = self._expect(TokenKind.LBRACKET, "expected '['")
        values: list[ValueNode] = []
        separators: list[Token] = []
        trailing_comma: Token | None = None

        mark = self.pos
        self._consume_trivia()
        if self._peek().kind == TokenKind.RBRACKET:
            return ArrayNode(lbracket, values, separators, None, self._advance())
        self.pos = mark

        while True:
            values.append(self._parse_value())
            self._consume_trivia()

            if self._peek().kind == TokenKind.COMMA:
                comma = self._advance()
                mark = self.pos
                self._consume_trivia()
                if self._peek().kind == TokenKind.RBRACKET:
                    trailing_comma = comma
                    rbracket = self._advance()
                    return ArrayNode(
                        lbracket, values, separators, trailing_comma, rbracket
                    )
                self.pos = mark
                separators.append(comma)
                continue

            if self._peek().kind == TokenKind.RBRACKET:
                return ArrayNode(
                    lbracket, values, separators, trailing_comma, self._advance()
                )

            raise self._error(self._peek(), "expected ',' or ']' after array element")

    def _parse_string(self) -> StringNode:
        token = self._expect(TokenKind.STRING, "expected string")
        try:
            decoded = json.loads(token.raw)
        except json.JSONDecodeError as exc:
            raise self._error(token, f"invalid string: {exc.msg}") from exc
        return StringNode(token, decoded)

    def _consume_trivia(self) -> list[Token]:
        trivia: list[Token] = []
        while self._peek().kind in TRIVIA_KINDS:
            trivia.append(self._advance())
        return trivia

    def _same_line_trailing_end(self, trivia: list[Token], fallback: int) -> int:
        end = fallback
        for token in trivia:
            if token.kind not in {TokenKind.LINE_COMMENT, TokenKind.BLOCK_COMMENT}:
                continue
            if (
                "\n" in self.source[fallback : token.start]
                or "\r" in self.source[fallback : token.start]
            ):
                break
            end = token.end
            if token.kind == TokenKind.LINE_COMMENT:
                break
        return end

    def _carried_leading_start(self, trivia: list[Token], fallback: int) -> int:
        """Return start offset for full-line comments carried with a member.

        Only comments that begin after indentation on their physical line are
        carried. Inline comments after a previous member/separator are left in
        the separator/layout slot.
        """
        carried_start: int | None = None
        for token in trivia:
            if token.kind not in {TokenKind.LINE_COMMENT, TokenKind.BLOCK_COMMENT}:
                continue
            if not self._is_full_line_token(token):
                carried_start = None
                continue
            line_start = self.source.rfind("\n", 0, token.start) + 1
            if line_start > 0 and self.source[line_start - 2 : line_start] == "\r\n":
                line_start -= 1
            if carried_start is None:
                carried_start = line_start
        return fallback if carried_start is None else carried_start

    def _is_full_line_token(self, token: Token) -> bool:
        if not self.source:
            return token.column == 1
        line_start = self.source.rfind("\n", 0, token.start) + 1
        prefix = self.source[line_start : token.start]
        return all(ch in " \t\r" for ch in prefix)

    def _expect(self, kind: TokenKind, message: str) -> Token:
        token = self._peek()
        if token.kind != kind:
            raise self._error(token, message)
        return self._advance()

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def _error(self, token: Token, message: str) -> JsoncSyntaxError:
        return JsoncSyntaxError(
            message, token.start, token.line, token.column, self.filename
        )
