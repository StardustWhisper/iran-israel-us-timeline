#!/usr/bin/env python3
"""Fix JSON with unescaped quotes inside string values (common LLM output bug).
Tracks nesting depth to find the true closing quote of each string.
"""
import sys
import json


def _is_valid_json_string_terminator(text, pos):
    """Check if the char at pos (after a quote) is a valid JSON string terminator.
    A closing quote is valid only if followed by one of: , : } ] or end-of-text.
    This prevents treating Chinese/curly quotes inside content as string delimiters.
    """
    if pos >= len(text):
        return True
    # Skip whitespace
    j = pos
    while j < len(text) and text[j] in ' \t\n\r':
        j += 1
    if j >= len(text):
        return True
    return text[j] in ',:}] \t\n\r'


def fix_json_quotes(text):
    """Fix JSON with unescaped `"` inside string values.

    This is a pragmatic repair pass for a common LLM failure mode:
    it emits quotes inside a JSON string without escaping them.

    Approach:
    - Track whether we're *inside* a JSON string.
    - When inside a string and we see a `"`:
      - If it looks like a real closing quote (followed by a valid JSON
        terminator like `, : } ]` after optional whitespace) → keep it.
      - Otherwise → escape it as `\\"`.

    Note: This is not a full JSON parser; it's designed to be robust for
    model outputs we control (single JSON object/array responses).
    """

    out = []
    i = 0
    n = len(text)
    in_string = False
    escaped = False

    while i < n:
        c = text[i]

        if not in_string:
            if c == '"':
                in_string = True
                out.append(c)
            else:
                out.append(c)
            i += 1
            continue

        # in_string
        if escaped:
            out.append(c)
            escaped = False
            i += 1
            continue

        if c == '\\':
            out.append(c)
            escaped = True
            i += 1
            continue

        if c == '"':
            if _is_valid_json_string_terminator(text, i + 1):
                in_string = False
                out.append(c)
            else:
                out.append('\\"')
            i += 1
            continue

        out.append(c)
        i += 1

    return ''.join(out)


def parse_messy_json(raw_text):
    """Try to parse JSON from raw CLI output that may have plugin messages prefix."""
    lines = raw_text.split('\n')
    clean_lines = [l for l in lines if not l.startswith('[plugins]')]
    text = '\n'.join(clean_lines)

    start = text.find('{')
    if start == -1:
        raise ValueError('no JSON found')

    raw_json = text[start:]

    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        pass

    fixed = fix_json_quotes(raw_json)
    return json.loads(fixed)


if __name__ == '__main__':
    text = sys.stdin.read()
    obj = parse_messy_json(text)
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
