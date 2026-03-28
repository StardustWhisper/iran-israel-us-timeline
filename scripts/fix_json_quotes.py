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
    """Fix unescaped quotes inside JSON string values.

    Walks the text character by character, tracking depth ({} and []).
    When we see an opening " (after :, {, [, or comma), we scan forward
    to find the VALID closing quote — one that is followed by a structural
    JSON character (, : } ]) or whitespace then structural char.
    Unescaped quotes that are NOT followed by valid terminators are treated
    as content and escaped.
    """
    result = []
    i = 0
    n = len(text)
    depth = 0  # net { minus } plus [ minus ]

    while i < n:
        c = text[i]

        if c == '{':
            depth += 1
            result.append(c)
            i += 1
        elif c == '}':
            depth -= 1
            result.append(c)
            i += 1
        elif c == '[':
            depth += 1
            result.append(c)
            i += 1
        elif c == ']':
            depth -= 1
            result.append(c)
            i += 1
        elif c == '"':
            # Opening a JSON string - find where it should end
            # Strategy: find the FIRST quote that is followed by a valid
            # JSON terminator (, : } ] or whitespace+terminator or EOF).
            # All earlier quotes are content and need escaping.
            j = i + 1
            closing_quote = -1

            while j < n:
                ch = text[j]
                if ch == '\\':
                    j += 2
                    continue
                if ch == '"':
                    if _is_valid_json_string_terminator(text, j + 1):
                        closing_quote = j
                        break
                    # Not a valid terminator — this quote is content, skip it
                    j += 1
                    continue
                if ch in ('}', ']') and depth > 0:
                    # Ran into a structural char without finding a closing quote
                    break
                j += 1

            if closing_quote > i:
                # Everything between i+1 and closing_quote is string content
                raw_content = text[i+1:closing_quote]
                # Escape any unescaped quotes in raw content
                fixed = []
                k = 0
                while k < len(raw_content):
                    if raw_content[k] == '\\' and k + 1 < len(raw_content):
                        fixed.append(raw_content[k:k+2])
                        k += 2
                    elif raw_content[k] == '"':
                        fixed.append('\\"')
                        k += 1
                    else:
                        fixed.append(raw_content[k])
                        k += 1
                result.append('"')
                result.append(''.join(fixed))
                result.append('"')
                i = closing_quote + 1
            else:
                # No closing quote found — leave as-is
                result.append(c)
                i += 1
        elif c == '\\':
            if i + 1 < n:
                result.append(text[i:i+2])
                i += 2
            else:
                result.append(c)
                i += 1
        else:
            result.append(c)
            i += 1

    return ''.join(result)


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
