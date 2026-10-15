"""检查所有 tr("...") 的中文 key 是否都在 i18n._EN 字典里(用 AST 解析)。"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 1) 从 i18n.py 提取 _EN 字典的全部 key
i18n_tree = ast.parse((ROOT / "src/ui/i18n.py").read_text(encoding="utf-8"))
dict_keys: set[str] = set()
for node in ast.walk(i18n_tree):
    target = None
    value = None
    if isinstance(node, ast.Assign):
        target = node.targets[0] if node.targets else None
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        target = node.target
        value = node.value
    if (isinstance(target, ast.Name) and target.id == "_EN"
            and isinstance(value, ast.Dict)):
        for k in value.keys:
            if k is not None:
                dict_keys.add(ast.literal_eval(k))

# 2) 扫描所有 tr(<字符串>) 调用(支持多行隐式拼接)
missing = []
for py in sorted((ROOT / "src").rglob("*.py")):
    if py.name == "i18n.py":
        continue
    tree = ast.parse(py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], (ast.Constant, ast.JoinedStr))):
            try:
                key = ast.literal_eval(node.args[0])
            except ValueError:
                continue  # f-string 等动态内容,跳过
            if isinstance(key, str) and key not in dict_keys:
                missing.append((py.relative_to(ROOT), node.lineno, key))

if missing:
    print(f"缺少 {len(missing)} 条翻译:")
    for path, line, key in missing:
        print(f"  {path}:{line}: {key!r}")
    sys.exit(1)
print(f"OK — 所有 tr() key 都有对应英文翻译(字典共 {len(dict_keys)} 条)")
