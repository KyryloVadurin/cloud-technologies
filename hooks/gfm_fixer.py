import re

def auto_wrap_mermaid_text(markdown):
    """
    Автоматично розбиває довгі тексти всередині блоків Mermaid на кілька рядків за допомогою <br/>
    """
    def wrap_label(text, max_chars=22):
        # Якщо текст вже має теги переносу або HTML, залишаємо як є
        if '<br' in text or '\n' in text:
            return text
        
        words = text.split()
        if not words:
            return text
        
        lines = []
        curr_line = []
        curr_len = 0
        
        for w in words:
            if curr_len + len(w) + (1 if curr_line else 0) > max_chars and curr_line:
                lines.append(" ".join(curr_line))
                curr_line = [w]
                curr_len = len(w)
            else:
                curr_line.append(w)
                curr_len += len(w) + (1 if len(curr_line) > 1 else 0)
        
        if curr_line:
            lines.append(" ".join(curr_line))
            
        return "<br/>".join(lines)

    def process_mermaid_block(match):
        code = match.group(1)
        
        # Регулярка шукає блоки Mermaid: [текст], ["текст"], (текст), {"текст"}, |текст|
        def replace_node(m):
            open_bracket = m.group(1)
            content = m.group(2)
            close_bracket = m.group(3)
            
            wrapped = wrap_label(content.strip(), max_chars=22)
            
            # Якщо додали <br/>, загортаємо в подвійні лапки для стабільного рендерингу Mermaid
            if '<br/>' in wrapped and not (open_bracket.endswith('"') and close_bracket.startswith('"')):
                open_bracket = open_bracket + '"'
                close_bracket = '"' + close_bracket
                
            return f"{open_bracket}{wrapped}{close_bracket}"

        # Патерн дужок Mermaid
        pattern = r'(\[\"|\[|\(\"|\(|\{\"|\{|\>\"|\>|\|)([^\[\]\(\)\{\}\|]+?)(\"\]|\]|\"\)|\)|\"\}|\}|\"\||\|)'
        fixed_code = re.sub(pattern, replace_node, code)
        return f"```mermaid\n{fixed_code}\n```"

    return re.sub(r'```mermaid\s*\n([\s\S]*?)\n```', process_mermaid_block, markdown)


def on_page_markdown(markdown, page, config, files):
    # 0. Автоматичний перенос довгих текстів у Mermaid
    markdown = auto_wrap_mermaid_text(markdown)

    # 1. Автоматично перетворюємо блоки ```math ... ``` на $$ ... $$
    markdown = re.sub(r'```math\s*\n([\s\S]*?)\n```', r'\n$$\n\1\n$$\n', markdown)

    # 2. Автоматично додаємо порожній рядок перед списками (- або * або 1.), якщо його немає
    markdown = re.sub(r'([^\n])\n([ \t]*[-*+]|\d+\.)\s+', r'\1\n\n\2 ', markdown)

    # 3. Замінюємо знак '<' у математичних блоках $$ на '\lt', щоб не ламався HTML
    def fix_math_tags(match):
        math_content = match.group(0)
        return re.sub(r'<(\s*[0-9a-zA-Z_])', r'\\lt \1', math_content)

    markdown = re.sub(r'\$\$[\s\S]*?\$\$', fix_math_tags, markdown)

    return markdown
