import re

def auto_wrap_mermaid_text(markdown):
    def process_mermaid_block(match):
        code = match.group(1)

        def sanitize_internal_quotes(m):
            prefix = m.group(1)
            content = m.group(2)
            suffix = m.group(3)
            cleaned_content = content.replace('"', "'")
            return f'{prefix}"{cleaned_content}"{suffix}'

        code = re.sub(r'(\[|\(|\{)\s*\"(.*?)\"\s*(\]|\)|\})', sanitize_internal_quotes, code)
        return f"```mermaid\n{code}\n```"

    return re.sub(r'```mermaid\s*\n([\s\S]*?)\n```', process_mermaid_block, markdown)


def convert_details_to_admonitions(markdown):
    """
    Конвертує сирі HTML <details> у нативні згортаємі блоки Material for MkDocs (??? note)
    з автоматичним виправленням відступів і списків.
    """
    def replace_details(match):
        summary = match.group(1).strip()
        content = match.group(2).strip()

        # 1. Забезпечуємо порожні рядки перед нумерованими та маркованими списками
        content = re.sub(r'([^\n])\n([ \t]*(\d+\.|[-*+])\s+)', r'\1\n\n\2', content)
        content = re.sub(r'(:\s*)\n([ \t]*[-*+]\s+)', r'\1\n\n\2', content)

        # 2. Робимо відступ 4 пробіли для кожного рядка контенту всередині блоку
        lines = content.split('\n')
        indented_lines = []
        for line in lines:
            if line.strip():
                indented_lines.append('    ' + line)
            else:
                indented_lines.append('')

        indented_content = '\n'.join(indented_lines)
        return f'??? note "{summary}"\n\n{indented_content}\n'

    # Шукаємо всі теги <details> ... <summary>Заголовок</summary> Текст </details>
    pattern = r'<details[^>]*>\s*<summary>(.*?)</summary>([\s\S]*?)</details>'
    return re.sub(pattern, replace_details, markdown)


def on_page_markdown(markdown, page, config, files):
    # 1. Автоматична конвертація спойлерів <details> у нативні блоки Material ??? note
    markdown = convert_details_to_admonitions(markdown)

    # 2. Обробка та виправлення синтаксису Mermaid
    markdown = auto_wrap_mermaid_text(markdown)

    # 3. Перетворення блоків ```math на $$ ... $$
    markdown = re.sub(r'```math\s*\n([\s\S]*?)\n```', r'\n$$\n\1\n$$\n', markdown)

    # 4. Гарантуємо порожні рядки перед списками у всьому документі
    markdown = re.sub(r'([^\n])\n([ \t]*[-*+]|\d+\.)\s+', r'\1\n\n\2 ', markdown)

    # 5. Заміна знаку '<' у формулах $$ на '\lt', щоб не ламався рендеринг
    def fix_math_tags(match):
        math_content = match.group(0)
        return re.sub(r'<(\s*[0-9a-zA-Z_\\])', r'\\lt \1', math_content)

    markdown = re.sub(r'\$\$[\s\S]*?\$\$', fix_math_tags, markdown)

    return markdown
