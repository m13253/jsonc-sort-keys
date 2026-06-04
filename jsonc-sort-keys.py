#!/usr/bin/env python3

import argparse
import enum
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path
from pprint import pformat, pprint
from tempfile import NamedTemporaryFile
from typing import IO, Optional, Sequence

Span = tuple[int, int]


class TokenType(StrEnum):
    SPACE = enum.auto()
    NEWLINE = enum.auto()

    MULTI_LINE_COMMENT = enum.auto()
    SINGLE_LINE_COMMENT = enum.auto()

    LEFT_CURLY_BRACKET = enum.auto()
    LEFT_SQUARE_BRACKET = enum.auto()
    RIGHT_CURLY_BRACKET = enum.auto()
    RIGHT_SQUARE_BRACKET = enum.auto()

    COLON = enum.auto()
    COMMA = enum.auto()

    STRING = enum.auto()

    # number, true, false, null, and other things we don't care
    OTHERS = enum.auto()


@dataclass
class Token:
    type: TokenType
    span: Optional[Span]
    raw: bytes

    def __repr__(self) -> str:
        return f"{self.type}({None if self.span is None else self.span[0]}, {None if self.span is None else self.span[1]}, {self.raw.decode('utf-8', 'replace')!r})"

    def dump(self, f: IO[bytes]) -> None:
        f.write(self.raw)

    def sort_key(self) -> bytes:
        match self.type:
            case TokenType.STRING:
                return unescape_string(self.raw)
            case TokenType.OTHERS:
                return self.raw
            case _:
                return b""


@dataclass
class CSTFragment(ABC):
    span: Optional[Span]
    leading: list[Token]

    def _dump_parts(
        self,
        parts: Sequence[
            Sequence["CSTFragment | Token"] | Optional["CSTFragment | Token"]
        ],
        f: IO[bytes],
    ) -> None:
        for i in self.leading:
            f.write(i.raw)
        for i in parts:
            if isinstance(i, (CSTFragment, Token)):
                i.dump(f)
            elif i is not None:
                for j in i:
                    j.dump(f)

    @abstractmethod
    def dump(self, f: IO[bytes]) -> None: ...

    @abstractmethod
    def sort_key(self) -> bytes: ...


@dataclass
class CSTNode(CSTFragment):
    pass


@dataclass
class CSTValue(CSTNode): ...


@dataclass
class CSTArrayItem(CSTFragment):
    value: list[CSTNode]
    comma: Optional[Token]
    comma_trailing: list[Token]  # Up to newline

    def dump(self, f: IO[bytes]) -> None:
        self._dump_parts(
            [
                self.value,
                self.comma,
                self.comma_trailing,
            ],
            f,
        )

    def sort_key(self) -> bytes:
        result = b"".join(i.sort_key() for i in self.value)
        return result


@dataclass
class CSTObjectItem(CSTFragment):
    key: list[CSTNode]
    colon: Optional[Token]
    value: list[CSTNode]
    comma: Optional[Token]
    comma_trailing: list[Token]  # Up to newline

    def dump(self, f: IO[bytes]) -> None:
        self._dump_parts(
            [
                self.key,
                self.colon,
                self.value,
                self.comma,
                self.comma_trailing,
            ],
            f,
        )

    def sort_key(self) -> bytes:
        # Actually the key would only be self.key[0], which must be a string,
        # but I wrote the program to be so stupidly permissive to all kinds of malformed input.
        # Here I might as well just throw all the garbage together to form a sort key.
        result = b"".join(i.sort_key() for i in self.key)
        return result


@dataclass
class CSTArray(CSTValue):
    opening_bracket: Token
    items: list[CSTArrayItem]
    items_trailing: list[Token]
    closing_bracket: Optional[Token]

    def dump(self, f: IO[bytes]) -> None:
        self._dump_parts(
            [
                self.opening_bracket,
                self.items,
                self.items_trailing,
                self.closing_bracket,
            ],
            f,
        )

    def sort_key(self) -> bytes:
        result = b",".join(i.sort_key() for i in self.items)
        return result


@dataclass
class CSTObject(CSTValue):
    opening_bracket: Token
    items_leading: list[Token]
    items: list[CSTObjectItem]
    items_trailing: list[Token]
    closing_bracket: Optional[Token]

    def dump(self, f: IO[bytes]) -> None:
        self._dump_parts(
            [
                self.opening_bracket,
                self.items_leading,
                self.items,
                self.items_trailing,
                self.closing_bracket,
            ],
            f,
        )

    def sort_key(self) -> bytes:
        result = b"[object Object]"  # Since I already made the code so stupid, let's put one more stupid joke here.
        result += b",".join(i.sort_key() for i in self.items)
        return result


@dataclass
class CSTPrimitive(CSTValue):
    value: Token

    def dump(self, f: IO[bytes]) -> None:
        self._dump_parts([self.value], f)

    def sort_key(self) -> bytes:
        return self.value.sort_key()


@dataclass
class CSTUndecodedToken(CSTNode):
    value: Token

    def dump(self, f: IO[bytes]) -> None:
        self._dump_parts([self.value], f)

    def sort_key(self) -> bytes:
        return self.value.sort_key()


def main() -> None:
    argparser = argparse.ArgumentParser(
        description="A small tool to sort keys of a JSONC file in Unicode order"
    )
    argparser.add_argument(
        "--dump-syntax-tree",
        action="store_true",
        help="Print the syntax tree instead of the JSONC file",
    )
    group = argparser.add_mutually_exclusive_group()
    group.add_argument(
        "--dangerous-overwrite-inplace",
        action="store_true",
        help="Dangerous: overwrite the input file in place",
    )
    group.add_argument("-o", "--output", type=Path, help="output file path")
    argparser.add_argument(
        "-p",
        "--permissive",
        action="store_true",
        help="tolerate all syntax errors and try to fix them at best effort",
    )
    argparser.add_argument("input", help="input file path")
    args = argparser.parse_args()

    if args.input == "-":
        doc = sys.stdin.buffer.read()
    else:
        with open(args.input, "rb") as f:
            doc = f.read()

    cst = parse(doc, args.permissive)
    transform(cst, doc, args.permissive)

    # The "inplace" of stdin is mapped to stdout,
    # thus "-" will fall through to the second branch.
    if args.dangerous_overwrite_inplace and args.input != "-":
        temp_path = None
        try:
            with NamedTemporaryFile(
                "wb", dir=Path(args.input).parent, delete=False
            ) as f:
                temp_path = f.name
                if args.dump_syntax_tree:
                    f.write(pformat(cst).encode("utf-8", "replace"))
                else:
                    dump(cst, f)

                try:
                    stat = os.stat(args.input)
                    os.chmod(temp_path, stat.st_mode)
                except Exception:
                    # Either stat() or chmod() is not available on this OS or filesystem.
                    pass

                os.replace(temp_path, args.input)
                temp_path = None

        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
    elif args.output is None or args.output == "-":
        if args.dump_syntax_tree:
            pprint(cst)
        else:
            dump(cst, sys.stdout.buffer)
    else:
        with open(args.output, "wb") as f:
            if args.dump_syntax_tree:
                f.write(pformat(cst).encode("utf-8", "replace"))
            else:
                dump(cst, f)


def parse(doc: bytes, permissive_mode: bool) -> list[CSTNode]:
    return parse_doc(tokenize_doc(doc, permissive_mode))


def transform(cst: list[CSTNode], doc: bytes, permissive_mode: bool) -> None:
    for i in cst:
        transform_node(i, doc, permissive_mode)


def dump(doc: list[CSTNode], f: IO[bytes]) -> None:
    for i in doc:
        i.dump(f)


def tokenize_doc(doc: bytes, permissive_mode: bool) -> list[Token]:
    tokens = []
    pos = 0
    while (token := tokenize_next(doc, pos, permissive_mode)) is not None:
        tokens.append(token)
        assert token.span is not None
        assert token.span[0] == pos
        assert token.span[1] > pos
        pos = token.span[1]
    return tokens


def tokenize_next(doc: bytes, start: int, permissive_mode: bool) -> Optional[Token]:

    class TokenizerState(StrEnum):
        START = enum.auto()

        SPACE = enum.auto()
        NEWLINE = enum.auto()

        QUOTE = enum.auto()
        QUOTE_BSLASH = enum.auto()
        QUOTE_BSLASH_U = enum.auto()
        QUOTE_BSLASH_U1 = enum.auto()
        QUOTE_BSLASH_U2 = enum.auto()
        QUOTE_BSLASH_U3 = enum.auto()

        SLASH = enum.auto()
        MULTI_LINE_COMMENT = enum.auto()
        MULTI_LINE_COMMENT_AST = enum.auto()
        SINGLE_LINE_COMMENT = enum.auto()
        SINGLE_LINE_COMMENT_CR = enum.auto()

        OTHERS = enum.auto()

    class CharCategory(Enum):
        OTHERS = 0x00
        SPACE = 0x09
        LF = 0x0A
        CR = 0x0D
        QUOTE = 0x22
        COMMA = 0x2C
        SLASH = 0x2F
        STAR = 0x2A
        HEX = 0x30
        COLON = 0x3A
        LEFT_SQUARE_BRACKET = 0x5B
        RIGHT_SQUARE_BRACKET = 0x5D
        BSLACH = 0x5C
        U = 0x75
        LEFT_CURLY_BRACKET = 0x7B
        RIGHT_CURLY_BRACKET = 0x7D

    def char_category(ch: int) -> CharCategory:
        match ch:
            case 0x09 | 0x20:
                return CharCategory.SPACE
            case 0x0A:
                return CharCategory.LF
            case 0x0D:
                return CharCategory.CR
            case 0x22:
                return CharCategory.QUOTE
            case 0x2C:
                return CharCategory.COMMA
            case 0x2F:
                return CharCategory.SLASH
            case 0x2A:
                return CharCategory.STAR
            case 0x3A:
                return CharCategory.COLON
            case 0x5B:
                return CharCategory.LEFT_SQUARE_BRACKET
            case 0x5D:
                return CharCategory.RIGHT_SQUARE_BRACKET
            case 0x5C:
                return CharCategory.BSLACH
            case 0x75:
                return CharCategory.U
            case 0x7B:
                return CharCategory.LEFT_CURLY_BRACKET
            case 0x7D:
                return CharCategory.RIGHT_CURLY_BRACKET
            case _ if 0x30 <= ch < 0x40 or 0x41 <= ch < 0x47 or 0x61 <= ch < 0x67:
                return CharCategory.HEX
            case _:
                return CharCategory.OTHERS

    state = TokenizerState.START
    for pos in range(start, len(doc) + 1):
        cat = char_category(doc[pos]) if pos < len(doc) else None
        match state:
            case TokenizerState.START:
                match cat:
                    case None:
                        return None
                    case CharCategory.SPACE:
                        state = TokenizerState.SPACE
                    case CharCategory.LF | CharCategory.CR:
                        state = TokenizerState.NEWLINE
                    case CharCategory.QUOTE:
                        state = TokenizerState.QUOTE
                    case CharCategory.COMMA:
                        return Token(
                            type=TokenType.COMMA,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.SLASH:
                        state = TokenizerState.SLASH
                    case CharCategory.COLON:
                        return Token(
                            type=TokenType.COLON,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.LEFT_SQUARE_BRACKET:
                        return Token(
                            type=TokenType.LEFT_SQUARE_BRACKET,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.RIGHT_SQUARE_BRACKET:
                        return Token(
                            type=TokenType.RIGHT_SQUARE_BRACKET,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.LEFT_CURLY_BRACKET:
                        return Token(
                            type=TokenType.LEFT_CURLY_BRACKET,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.RIGHT_CURLY_BRACKET:
                        return Token(
                            type=TokenType.RIGHT_CURLY_BRACKET,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case _:
                        state = TokenizerState.OTHERS
            case TokenizerState.SPACE:
                match cat:
                    case CharCategory.SPACE:
                        pass
                    case _:
                        return Token(
                            type=TokenType.SPACE,
                            span=(start, pos),
                            raw=doc[start:pos],
                        )
            case TokenizerState.NEWLINE:
                match cat:
                    case CharCategory.LF | CharCategory.CR:
                        pass
                    case _:
                        return Token(
                            type=TokenType.NEWLINE,
                            span=(start, pos),
                            raw=doc[start:pos],
                        )
            case TokenizerState.QUOTE:
                match cat:
                    case None:
                        report_syntax_error(
                            doc,
                            pos,
                            permissive_mode,
                            "missing '\"'",
                        )
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos),
                            raw=doc[start:pos] + b'"',
                        )
                    case CharCategory.QUOTE:
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.BSLACH:
                        state = TokenizerState.QUOTE_BSLASH
            case TokenizerState.QUOTE_BSLASH:
                match cat:
                    case None:
                        # The user actually needs to complete the last escape sequence first, then add '"'.
                        report_syntax_error(
                            doc,
                            pos,
                            permissive_mode,
                            "missing '\"'",
                        )
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos),
                            raw=doc[start:pos] + b'\\"',
                        )
                    case CharCategory.U:
                        state = TokenizerState.QUOTE_BSLASH_U
                    case _:
                        state = TokenizerState.QUOTE
            case TokenizerState.QUOTE_BSLASH_U:
                match cat:
                    case None:
                        report_syntax_error(
                            doc,
                            pos,
                            permissive_mode,
                            "missing '\"'",
                        )
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos),
                            raw=doc[start:pos] + b'"',
                        )
                    case CharCategory.QUOTE:
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.HEX:
                        state = TokenizerState.QUOTE_BSLASH_U1
                    case CharCategory.BSLACH:
                        state = TokenizerState.QUOTE_BSLASH
                    case _:
                        state = TokenizerState.QUOTE
            case TokenizerState.QUOTE_BSLASH_U1:
                match cat:
                    case None:
                        report_syntax_error(
                            doc,
                            pos,
                            permissive_mode,
                            "missing '\"'",
                        )
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos),
                            raw=doc[start:pos] + b'"',
                        )
                    case CharCategory.QUOTE:
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.HEX:
                        state = TokenizerState.QUOTE_BSLASH_U2
                    case CharCategory.BSLACH:
                        state = TokenizerState.QUOTE_BSLASH
                    case _:
                        state = TokenizerState.QUOTE
            case TokenizerState.QUOTE_BSLASH_U2:
                match cat:
                    case None:
                        report_syntax_error(
                            doc,
                            pos,
                            permissive_mode,
                            "missing '\"'",
                        )
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos),
                            raw=doc[start:pos] + b'"',
                        )
                    case CharCategory.QUOTE:
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.HEX:
                        state = TokenizerState.QUOTE_BSLASH_U3
                    case CharCategory.BSLACH:
                        state = TokenizerState.QUOTE_BSLASH
                    case _:
                        state = TokenizerState.QUOTE
            case TokenizerState.QUOTE_BSLASH_U3:
                match cat:
                    case None:
                        report_syntax_error(
                            doc,
                            pos,
                            permissive_mode,
                            "missing '\"'",
                        )
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos),
                            raw=doc[start:pos] + b'"',
                        )
                    case CharCategory.QUOTE:
                        return Token(
                            type=TokenType.STRING,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.BSLACH:
                        state = TokenizerState.QUOTE_BSLASH
                    case _:
                        state = TokenizerState.QUOTE
            case TokenizerState.SLASH:
                match cat:
                    case None:
                        return Token(
                            type=TokenType.OTHERS,
                            span=(start, pos),
                            raw=doc[start:pos],
                        )
                    case CharCategory.STAR:
                        state = TokenizerState.MULTI_LINE_COMMENT
                    case CharCategory.SLASH:
                        state = TokenizerState.SINGLE_LINE_COMMENT
                    case _:
                        state = TokenizerState.OTHERS
            case TokenizerState.MULTI_LINE_COMMENT:
                match cat:
                    case None:
                        report_syntax_error(
                            doc,
                            pos,
                            permissive_mode,
                            'missing "*/"',
                        )
                        return Token(
                            type=TokenType.MULTI_LINE_COMMENT,
                            span=(start, pos),
                            raw=doc[start:pos] + b"*/",
                        )
                    case CharCategory.STAR:
                        state = TokenizerState.MULTI_LINE_COMMENT_AST
            case TokenizerState.MULTI_LINE_COMMENT_AST:
                match cat:
                    case None:
                        report_syntax_error(
                            doc,
                            pos,
                            permissive_mode,
                            'missing "*/"',
                        )
                        return Token(
                            type=TokenType.MULTI_LINE_COMMENT,
                            span=(start, pos),
                            raw=doc[start:pos] + b"/",
                        )
                    case CharCategory.SLASH:
                        return Token(
                            type=TokenType.MULTI_LINE_COMMENT,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case _:
                        state = TokenizerState.MULTI_LINE_COMMENT
            case TokenizerState.SINGLE_LINE_COMMENT:
                match cat:
                    case None:
                        return Token(
                            type=TokenType.SINGLE_LINE_COMMENT,
                            span=(start, pos),
                            raw=doc[start:pos],
                        )
                    case CharCategory.LF:
                        return Token(
                            type=TokenType.SINGLE_LINE_COMMENT,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case CharCategory.CR:
                        state = TokenizerState.SINGLE_LINE_COMMENT_CR
            case TokenizerState.SINGLE_LINE_COMMENT_CR:
                match cat:
                    case CharCategory.LF:
                        return Token(
                            type=TokenType.SINGLE_LINE_COMMENT,
                            span=(start, pos + 1),
                            raw=doc[start : pos + 1],
                        )
                    case _:
                        return Token(
                            type=TokenType.SINGLE_LINE_COMMENT,
                            span=(start, pos),
                            raw=doc[start:pos],
                        )
            case TokenizerState.OTHERS:
                match cat:
                    case (
                        None
                        | CharCategory.SPACE
                        | CharCategory.LF
                        | CharCategory.CR
                        | CharCategory.QUOTE
                        | CharCategory.COMMA
                        | CharCategory.SLASH
                        | CharCategory.COLON
                        | CharCategory.LEFT_SQUARE_BRACKET
                        | CharCategory.RIGHT_SQUARE_BRACKET
                        | CharCategory.LEFT_CURLY_BRACKET
                        | CharCategory.RIGHT_CURLY_BRACKET
                    ):
                        return Token(
                            type=TokenType.OTHERS,
                            span=(start, pos),
                            raw=doc[start:pos],
                        )

    raise RuntimeError("Unreachable")


def unescape_string(raw: bytes) -> bytes:

    class DecoderState(StrEnum):
        START = enum.auto()
        BSLASH = enum.auto()
        BSLASH_U = enum.auto()
        BSLASH_U1 = enum.auto()
        BSLASH_U2 = enum.auto()
        BSLASH_U3 = enum.auto()

    result = []
    pending_ucs2 = []

    def decode_hex(c: int) -> Optional[int]:
        if 0x30 <= c < 0x3A:
            return c & 0x0F
        elif 0x41 <= c < 0x47:
            return c - 0x37
        elif 0x61 <= c < 0x67:
            return c - 0x57
        else:
            return None

    def flush_codepoint(c: int) -> None:
        assert 0 <= c <= 0x10FFFF
        if c < 0x80:
            result.append(c & 0x7F)
        elif c < 0x0800:
            result.append((c >> 6) | 0xC0)
            result.append(c & 0x3F | 0x80)
        elif c < 0x10000:
            result.append((c >> 12) | 0xE0)
            result.append((c >> 6) & 0x3F | 0x80)
            result.append(c & 0x3F | 0x80)
        else:
            result.append((c >> 18) & 0x7 | 0xF0)
            result.append((c >> 12) & 0x3F | 0x80)
            result.append((c >> 6) & 0x3F | 0x80)
            result.append(c & 0x3F | 0x80)

    def flush_pending_escape() -> None:
        while len(pending_ucs2) != 0:
            if (
                len(pending_ucs2) > 1
                and pending_ucs2[0] & 0xDC00 == 0xD800
                and pending_ucs2[1] & 0xDC00 == 0xDC00
            ):
                high = pending_ucs2.pop(0)
                low = pending_ucs2.pop(0)
                c = ((high & 0x3FF) << 10 | (low & 0x3FF)) + 0x10000
                flush_codepoint(c)
            else:
                # The string may be invalid Unicode, but JSON allows such strings.
                # We will encode as WTF-8 so we at least have a sorting key.
                flush_codepoint(pending_ucs2.pop(0))

    state = DecoderState.START
    for c in raw:
        match state:
            case DecoderState.START:
                match c:
                    case 0x22:  # '"'
                        pass
                    case 0x5C:  # '\\'
                        state = DecoderState.BSLASH
                    case _:
                        flush_pending_escape()
                        result.append(c)
            case DecoderState.BSLASH:
                match c:
                    case 0x62:
                        flush_pending_escape()
                        result.append(0x08)
                        state = DecoderState.START
                    case 0x66:
                        flush_pending_escape()
                        result.append(0x0C)
                        state = DecoderState.START
                    case 0x6E:
                        flush_pending_escape()
                        result.append(0x0A)
                        state = DecoderState.START
                    case 0x72:
                        flush_pending_escape()
                        result.append(0x0D)
                        state = DecoderState.START
                    case 0x74:
                        flush_pending_escape()
                        result.append(0x09)
                        state = DecoderState.START
                    case 0x75:
                        pending_ucs2.append(0)
                        state = DecoderState.BSLASH_U
                    case _:
                        flush_pending_escape()
                        result.append(c)
                        state = DecoderState.START
            case DecoderState.BSLASH_U:
                match c:
                    case 0x22:
                        state = DecoderState.START
                    case 0x5C:
                        state = DecoderState.BSLASH
                    case _:
                        digit = decode_hex(c)
                        if digit is None:
                            flush_pending_escape()
                            result.append(c)
                            state = DecoderState.START
                        else:
                            pending_ucs2[-1] = digit
                            state = DecoderState.BSLASH_U1
            case DecoderState.BSLASH_U1:
                match c:
                    case 0x22:
                        state = DecoderState.START
                    case 0x5C:
                        state = DecoderState.BSLASH
                    case _:
                        digit = decode_hex(c)
                        if digit is None:
                            flush_pending_escape()
                            result.append(c)
                            state = DecoderState.START
                        else:
                            pending_ucs2[-1] = (pending_ucs2[-1] << 4) | digit
                            state = DecoderState.BSLASH_U2
            case DecoderState.BSLASH_U2:
                match c:
                    case 0x22:
                        state = DecoderState.START
                    case 0x5C:
                        state = DecoderState.BSLASH
                    case _:
                        digit = decode_hex(c)
                        if digit is None:
                            flush_pending_escape()
                            result.append(c)
                            state = DecoderState.START
                        else:
                            pending_ucs2[-1] = (pending_ucs2[-1] << 4) | digit
                            state = DecoderState.BSLASH_U3
            case DecoderState.BSLASH_U3:
                match c:
                    case 0x22:
                        state = DecoderState.START
                    case 0x5C:
                        state = DecoderState.BSLASH
                    case _:
                        digit = decode_hex(c)
                        if digit is None:
                            flush_pending_escape()
                            result.append(c)
                        else:
                            pending_ucs2[-1] = (pending_ucs2[-1] << 4) | digit
                        state = DecoderState.START
    flush_pending_escape()
    return bytes(result)


def parse_doc(doc: list[Token]) -> list[CSTNode]:
    results = []
    pos = 0
    while pos < len(doc):
        value, pos = try_parse_value(doc, pos)
        if value is not None:
            results.append(value)
    return results


def try_parse_value(doc: list[Token], start: int) -> tuple[Optional[CSTNode], int]:
    if start >= len(doc):
        return None, start
    token = doc[start]
    value, pos = parse_value(doc, start)
    if value is None:
        return CSTUndecodedToken(
            span=(start, start + 1), leading=[], value=token
        ), start + 1
    else:
        return value, pos


def parse_value(doc: list[Token], start: int) -> tuple[Optional[CSTValue], int]:
    leading, span, pos = parse_wsc(doc, None, start)
    if pos >= len(doc):
        return None, start

    opening_token = doc[pos]
    pos += 1
    match opening_token.type:
        case TokenType.LEFT_CURLY_BRACKET:
            items_leading, span, pos = parse_wsc_until_newline(doc, span, pos)
            items = []
            while (v := parse_object_item(doc, pos))[0] is not None:
                items.append(v[0])
                span = merge_span(span, v[0].span)
                pos = v[1]
            items_trailing = []
            closing_bracket = None
            while pos < len(doc):
                token = doc[pos]
                match token.type:
                    case TokenType.RIGHT_CURLY_BRACKET:
                        closing_bracket = token
                        span = merge_span(span, token.span)
                        pos += 1
                        break
                    case TokenType.RIGHT_SQUARE_BRACKET:
                        break
                    case _:
                        items_trailing.append(token)
                        span = merge_span(span, token.span)
                pos += 1
            return CSTObject(
                span=span,
                leading=leading,
                opening_bracket=opening_token,
                items_leading=items_leading,
                items=items,
                items_trailing=items_trailing,
                closing_bracket=closing_bracket,
            ), pos

        case TokenType.LEFT_SQUARE_BRACKET:
            items = []
            while (v := parse_array_item(doc, pos))[0] is not None:
                items.append(v[0])
                span = merge_span(span, v[0].span)
                pos = v[1]
            items_trailing = []
            closing_bracket = None
            while pos < len(doc):
                token = doc[pos]
                match token.type:
                    case TokenType.RIGHT_CURLY_BRACKET:
                        break
                    case TokenType.RIGHT_SQUARE_BRACKET:
                        closing_bracket = token
                        span = merge_span(span, token.span)
                        pos += 1
                        break
                    case _:
                        items_trailing.append(token)
                        span = merge_span(span, token.span)
                pos += 1
            return CSTArray(
                span=span,
                leading=leading,
                opening_bracket=opening_token,
                items=items,
                items_trailing=items_trailing,
                closing_bracket=closing_bracket,
            ), pos

        case TokenType.STRING | TokenType.OTHERS:
            span = merge_span(span, opening_token.span)
            return CSTPrimitive(span=span, leading=leading, value=opening_token), pos

        case _:
            return None, start


def parse_array_item(
    doc: list[Token], start: int
) -> tuple[Optional[CSTArrayItem], int]:
    leading, span, pos = parse_wsc(doc, None, start)

    value = []
    while (v := try_parse_value(doc, pos))[0] is not None:
        if isinstance(v[0], CSTUndecodedToken) and v[0].value.type in (
            TokenType.COMMA,
            TokenType.RIGHT_CURLY_BRACKET,
            TokenType.RIGHT_SQUARE_BRACKET,
        ):
            break
        value.append(v[0])
        span = merge_span(span, v[0].span)
        pos = v[1]

    comma = None
    if pos < len(doc):
        token = doc[pos]
        if token.type == TokenType.COMMA:
            comma = token
            span = merge_span(span, token.span)
            pos += 1

    if len(value) == 0 and comma is None:
        return None, start

    comma_trailing, span, pos = parse_wsc_until_newline(doc, span, pos)

    return CSTArrayItem(
        span=span,
        leading=leading,
        value=value,
        comma=comma,
        comma_trailing=comma_trailing,
    ), pos


def parse_object_item(
    doc: list[Token], start: int
) -> tuple[Optional[CSTObjectItem], int]:
    leading, span, pos = parse_wsc(doc, None, start)

    key = []
    while (k := try_parse_value(doc, pos))[0] is not None:
        if isinstance(k[0], CSTUndecodedToken) and k[0].value.type in (
            TokenType.COLON,
            TokenType.COMMA,
            TokenType.RIGHT_CURLY_BRACKET,
            TokenType.RIGHT_SQUARE_BRACKET,
        ):
            break
        key.append(k[0])
        span = merge_span(span, k[0].span)
        pos = k[1]

    colon = None
    if pos < len(doc):
        token = doc[pos]
        if token.type == TokenType.COLON:
            colon = token
            span = merge_span(span, token.span)
            pos += 1

    value = []
    while (v := try_parse_value(doc, pos))[0] is not None:
        if isinstance(v[0], CSTUndecodedToken) and v[0].value.type in (
            TokenType.COMMA,
            TokenType.RIGHT_CURLY_BRACKET,
            TokenType.RIGHT_SQUARE_BRACKET,
        ):
            break
        value.append(v[0])
        span = merge_span(span, v[0].span)
        pos = v[1]

    comma = None
    if pos < len(doc):
        token = doc[pos]
        if token.type == TokenType.COMMA:
            comma = token
            span = merge_span(span, token.span)
            pos += 1

    if len(key) == 0 and colon is None and len(value) == 0 and comma is None:
        return None, start

    comma_trailing, span, pos = parse_wsc_until_newline(doc, span, pos)

    return CSTObjectItem(
        span=span,
        leading=leading,
        key=key,
        colon=colon,
        value=value,
        comma=comma,
        comma_trailing=comma_trailing,
    ), pos


def parse_wsc(
    doc: list[Token], span: Optional[Span], start: int
) -> tuple[list[Token], Optional[Span], int]:
    tokens = []
    pos = start
    while pos < len(doc):
        token = doc[pos]
        match token.type:
            case (
                TokenType.SPACE
                | TokenType.NEWLINE
                | TokenType.MULTI_LINE_COMMENT
                | TokenType.SINGLE_LINE_COMMENT
            ):
                tokens.append(token)
                span = merge_span(span, token.span)
            case _:
                break
        pos += 1
    return tokens, span, pos


def parse_wsc_until_newline(
    doc: list[Token], span: Optional[Span], start: int
) -> tuple[list[Token], Optional[Span], int]:
    tokens = []
    new_span = span
    pos = start
    while pos < len(doc):
        token = doc[pos]
        match token.type:
            case TokenType.SPACE | TokenType.MULTI_LINE_COMMENT:
                tokens.append(token)
                new_span = merge_span(new_span, token.span)
            case TokenType.NEWLINE | TokenType.SINGLE_LINE_COMMENT:
                tokens.append(token)
                new_span = merge_span(new_span, token.span)
                pos += 1
                break
            case TokenType.RIGHT_CURLY_BRACKET | TokenType.RIGHT_SQUARE_BRACKET:
                break
            case _:
                return [], span, start
        pos += 1
    return tokens, new_span, pos


def merge_span(old_span: Optional[Span], new_span: Optional[Span]) -> Optional[Span]:
    if old_span is None:
        return new_span
    elif new_span is None:
        return old_span
    else:
        return min(old_span[0], new_span[0]), max(old_span[1], new_span[1])


def transform_node(value: CSTNode, doc: bytes, permissive_mode: bool):
    if isinstance(value, CSTArray):
        for i, v in enumerate(value.items):
            for j in v.value:
                transform_node(j, doc, permissive_mode)
        if value.closing_bracket is None:
            report_syntax_error(
                doc,
                None if value.span is None else value.span[1],
                permissive_mode,
                'missing "]"',
            )
            value.closing_bracket = Token(
                type=TokenType.RIGHT_SQUARE_BRACKET,
                span=None,
                raw=b"]",
            )
    elif isinstance(value, CSTObject):
        value.items.sort(key=CSTObjectItem.sort_key)
        for i, v in enumerate(value.items):
            for j in v.key:
                transform_node(j, doc, permissive_mode)
            for j in v.value:
                transform_node(j, doc, permissive_mode)
            if i == len(value.items) - 1:
                v.comma = None
            elif v.comma is None:
                v.comma = Token(
                    type=TokenType.COMMA,
                    span=None,
                    raw=b",",
                )
                while (
                    len(v.value) != 0
                    and isinstance(v.value[-1], CSTUndecodedToken)
                    and (token := v.value[-1].value).type
                    in (
                        TokenType.SPACE,
                        TokenType.NEWLINE,
                        TokenType.SINGLE_LINE_COMMENT,
                    )
                ):
                    v.comma_trailing.insert(0, token)
                    del v.value[-1]
        if value.closing_bracket is None:
            report_syntax_error(
                doc,
                None if value.span is None else value.span[1],
                permissive_mode,
                'missing "}"',
            )
            value.closing_bracket = Token(
                type=TokenType.RIGHT_CURLY_BRACKET,
                span=None,
                raw=b"}",
            )


def report_syntax_error(
    doc: bytes, offset: Optional[int], permissive_mode: bool, message: str
) -> None:
    if permissive_mode:
        return
    if offset is None:
        print(
            f"unrecoverable syntax error: {message}",
            file=sys.stderr,
        )
    else:
        row = (
            doc.count(b"\n", 0, offset)
            + doc.count(b"\r", 0, offset)
            - doc.count(b"\r\n", 0, offset)
            + 1
        )
        col = offset - max(doc.rfind(b"\n", 0, offset), doc.rfind(b"\r", 0, offset))
        print(
            f"unrecoverable syntax error at {row} {col}: {message}",
            file=sys.stderr,
        )
    sys.exit(1)


if __name__ == "__main__":
    main()
