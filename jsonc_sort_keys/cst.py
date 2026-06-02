from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Union


class TokenKind(Enum):
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    COLON = auto()
    COMMA = auto()
    STRING = auto()
    NUMBER = auto()
    TRUE = auto()
    FALSE = auto()
    NULL = auto()
    WHITESPACE = auto()
    LINE_COMMENT = auto()
    BLOCK_COMMENT = auto()
    EOF = auto()


TRIVIA_KINDS = {TokenKind.WHITESPACE, TokenKind.LINE_COMMENT, TokenKind.BLOCK_COMMENT}


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    raw: str
    start: int
    end: int
    line: int
    column: int


@dataclass
class Document:
    leading_trivia: list[Token]
    value: "ValueNode"
    trailing_trivia: list[Token]
    eof: Token

    @property
    def start(self) -> int:
        if self.leading_trivia:
            return self.leading_trivia[0].start
        return self.value.start

    @property
    def end(self) -> int:
        return self.eof.end


@dataclass
class StringNode:
    token: Token
    decoded: str

    @property
    def start(self) -> int:
        return self.token.start

    @property
    def end(self) -> int:
        return self.token.end


@dataclass
class NumberNode:
    token: Token

    @property
    def start(self) -> int:
        return self.token.start

    @property
    def end(self) -> int:
        return self.token.end


@dataclass
class LiteralNode:
    token: Token

    @property
    def start(self) -> int:
        return self.token.start

    @property
    def end(self) -> int:
        return self.token.end


@dataclass
class MemberNode:
    key: StringNode
    colon: Token
    value: "ValueNode"
    index: int
    leading_start: int
    trailing_end: int

    @property
    def start(self) -> int:
        return self.key.start

    @property
    def end(self) -> int:
        return self.value.end

    @property
    def sort_key(self) -> str:
        return self.key.decoded


@dataclass
class ObjectNode:
    lbrace: Token
    members: list[MemberNode]
    separators: list[Token]
    trailing_comma: Token | None
    rbrace: Token

    @property
    def start(self) -> int:
        return self.lbrace.start

    @property
    def end(self) -> int:
        return self.rbrace.end


@dataclass
class ArrayNode:
    lbracket: Token
    values: list["ValueNode"]
    separators: list[Token]
    trailing_comma: Token | None
    rbracket: Token

    @property
    def start(self) -> int:
        return self.lbracket.start

    @property
    def end(self) -> int:
        return self.rbracket.end


ValueNode = Union[ObjectNode, ArrayNode, StringNode, NumberNode, LiteralNode]
