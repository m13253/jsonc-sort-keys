from __future__ import annotations

from .cst import Token, TokenKind
from .errors import JsoncSyntaxError


class Lexer:
    def __init__(self, source: str, filename: str | None = None):
        self.source = source
        self.filename = filename
        self.length = len(source)
        self.pos = 0
        self.line = 1
        self.column = 1

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while self.pos < self.length:
            ch = self.source[self.pos]
            if ch in " \t\r\n":
                tokens.append(self._scan_whitespace())
            elif ch == "/" and self._peek(1) == "/":
                tokens.append(self._scan_line_comment())
            elif ch == "/" and self._peek(1) == "*":
                tokens.append(self._scan_block_comment())
            elif ch == '"':
                tokens.append(self._scan_string())
            elif ch == "-" or ch.isdigit():
                tokens.append(self._scan_number())
            elif ch == "{":
                tokens.append(self._simple(TokenKind.LBRACE))
            elif ch == "}":
                tokens.append(self._simple(TokenKind.RBRACE))
            elif ch == "[":
                tokens.append(self._simple(TokenKind.LBRACKET))
            elif ch == "]":
                tokens.append(self._simple(TokenKind.RBRACKET))
            elif ch == ":":
                tokens.append(self._simple(TokenKind.COLON))
            elif ch == ",":
                tokens.append(self._simple(TokenKind.COMMA))
            elif self.source.startswith("true", self.pos):
                tokens.append(self._keyword(TokenKind.TRUE, "true"))
            elif self.source.startswith("false", self.pos):
                tokens.append(self._keyword(TokenKind.FALSE, "false"))
            elif self.source.startswith("null", self.pos):
                tokens.append(self._keyword(TokenKind.NULL, "null"))
            else:
                raise self._error(f"unexpected character {ch!r}")

        tokens.append(
            Token(TokenKind.EOF, "", self.pos, self.pos, self.line, self.column)
        )
        return tokens

    def _simple(self, kind: TokenKind) -> Token:
        start, line, column = self.pos, self.line, self.column
        raw = self.source[self.pos]
        self._advance_one()
        return Token(kind, raw, start, self.pos, line, column)

    def _keyword(self, kind: TokenKind, text: str) -> Token:
        start, line, column = self.pos, self.line, self.column
        end = self.pos + len(text)
        if end < self.length and (
            self.source[end].isalnum() or self.source[end] == "_"
        ):
            raise self._error(f"unexpected token starting with {text!r}")
        self._advance_text(text)
        return Token(kind, text, start, self.pos, line, column)

    def _scan_whitespace(self) -> Token:
        start, line, column = self.pos, self.line, self.column
        while self.pos < self.length and self.source[self.pos] in " \t\r\n":
            self._advance_one()
        return Token(
            TokenKind.WHITESPACE,
            self.source[start : self.pos],
            start,
            self.pos,
            line,
            column,
        )

    def _scan_line_comment(self) -> Token:
        start, line, column = self.pos, self.line, self.column
        self._advance_text("//")
        while self.pos < self.length and self.source[self.pos] not in "\r\n":
            self._advance_one()
        return Token(
            TokenKind.LINE_COMMENT,
            self.source[start : self.pos],
            start,
            self.pos,
            line,
            column,
        )

    def _scan_block_comment(self) -> Token:
        start, line, column = self.pos, self.line, self.column
        self._advance_text("/*")
        while self.pos < self.length:
            if self.source[self.pos] == "*" and self._peek(1) == "/":
                self._advance_text("*/")
                return Token(
                    TokenKind.BLOCK_COMMENT,
                    self.source[start : self.pos],
                    start,
                    self.pos,
                    line,
                    column,
                )
            self._advance_one()
        raise JsoncSyntaxError(
            "unterminated block comment", start, line, column, self.filename
        )

    def _scan_string(self) -> Token:
        start, line, column = self.pos, self.line, self.column
        self._advance_one()  # opening quote
        while self.pos < self.length:
            ch = self.source[self.pos]
            if ch == '"':
                self._advance_one()
                return Token(
                    TokenKind.STRING,
                    self.source[start : self.pos],
                    start,
                    self.pos,
                    line,
                    column,
                )
            if ch == "\\":
                self._advance_one()
                if self.pos >= self.length:
                    raise self._error_at(
                        "unterminated string escape", start, line, column
                    )
                esc = self.source[self.pos]
                if esc in '"\\/bfnrt':
                    self._advance_one()
                elif esc == "u":
                    self._advance_one()
                    for _ in range(4):
                        if (
                            self.pos >= self.length
                            or self.source[self.pos] not in "0123456789abcdefABCDEF"
                        ):
                            raise self._error("invalid unicode escape")
                        self._advance_one()
                else:
                    raise self._error(f"invalid string escape \\{esc}")
                continue
            if ord(ch) < 0x20:
                raise self._error("unescaped control character in string")
            self._advance_one()
        raise JsoncSyntaxError(
            "unterminated string", start, line, column, self.filename
        )

    def _scan_number(self) -> Token:
        start, line, column = self.pos, self.line, self.column
        if self._peek() == "-":
            self._advance_one()
            if self.pos >= self.length:
                raise self._error_at("invalid number", start, line, column)

        if self._peek() == "0":
            self._advance_one()
            if self.pos < self.length and self._peek().isdigit():
                raise self._error("invalid number: leading zero is not allowed")
        elif self._peek() and "1" <= self._peek() <= "9":
            while self.pos < self.length and self._peek().isdigit():
                self._advance_one()
        else:
            raise self._error_at("invalid number", start, line, column)

        if self._peek() == ".":
            self._advance_one()
            if self.pos >= self.length or not self._peek().isdigit():
                raise self._error("invalid number: expected digit after decimal point")
            while self.pos < self.length and self._peek().isdigit():
                self._advance_one()

        if self._peek() in {"e", "E"}:
            self._advance_one()
            if self._peek() in {"+", "-"}:
                self._advance_one()
            if self.pos >= self.length or not self._peek().isdigit():
                raise self._error("invalid number: expected exponent digit")
            while self.pos < self.length and self._peek().isdigit():
                self._advance_one()

        if self.pos < self.length and (self._peek().isalpha() or self._peek() == "_"):
            raise self._error("invalid number")

        return Token(
            TokenKind.NUMBER,
            self.source[start : self.pos],
            start,
            self.pos,
            line,
            column,
        )

    def _peek(self, ahead: int = 0) -> str:
        index = self.pos + ahead
        if index >= self.length:
            return ""
        return self.source[index]

    def _advance_text(self, text: str) -> None:
        for _ in text:
            self._advance_one()

    def _advance_one(self) -> None:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\r":
            if self.pos < self.length and self.source[self.pos] == "\n":
                self.pos += 1
            self.line += 1
            self.column = 1
        elif ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1

    def _error(self, message: str) -> JsoncSyntaxError:
        return JsoncSyntaxError(
            message, self.pos, self.line, self.column, self.filename
        )

    def _error_at(
        self, message: str, offset: int, line: int, column: int
    ) -> JsoncSyntaxError:
        return JsoncSyntaxError(message, offset, line, column, self.filename)
