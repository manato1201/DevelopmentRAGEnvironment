"""Guide の単体テストで共有する、偽の Houdini（FakeHou）。パスで作る、小さなノードの木。

使い方:
    world = make_world({"/obj/geo1": "geo", "/obj/geo1/scatter1": "scatter::2.0"}, pwd="/obj/geo1")
    hou = world.hou
"""
from __future__ import annotations

import types


class FakeCategory:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class FakeTemplate:
    """hou.ParmTemplate の、メニュー・チェックボックスに関わる部分だけの偽物。"""

    def __init__(self, name, label, kind="Float", items=(), labels=(), default=0):
        self._name, self._label, self._kind = name, label, kind
        self._items, self._labels, self._default = tuple(items), tuple(labels), default

    def name(self): return self._name
    def label(self): return self._label
    def type(self): return types.SimpleNamespace(name=lambda: self._kind)
    def menuItems(self): return self._items
    def menuLabels(self): return self._labels or self._items
    def defaultValue(self): return (self._default,)


class FakeType:
    def __init__(self, name, label="", category="Sop", templates=()):
        self._name, self._label, self._category = name, label or name, category
        self.templates = {t.name(): t for t in templates}

    def name(self): return self._name
    def description(self): return self._label
    def category(self): return FakeCategory(self._category)

    def parmTemplateGroup(self):
        return types.SimpleNamespace(find=lambda name: self.templates.get(name))


class FakeParm:
    def __init__(self, template):
        self._template = template

    def parmTemplate(self): return self._template


class FakeNode:
    def __init__(self, world, path, type_name="null", label="", templates=()):
        self.world = world
        self._path = path
        self._type = FakeType(type_name, label or type_name, templates=templates)
        self.current = False
        self.selected = False

    def name(self): return self._path.rsplit("/", 1)[-1]
    def path(self): return self._path
    def type(self): return self._type

    def parent(self):
        parent_path = self._path.rsplit("/", 1)[0] or "/"
        return self.world.nodes.get(parent_path)

    def children(self):
        prefix = self._path.rstrip("/") + "/"
        return [n for p, n in self.world.nodes.items() if p.startswith(prefix) and "/" not in p[len(prefix):]]

    def allSubChildren(self):
        prefix = self._path.rstrip("/") + "/"
        return [n for p, n in self.world.nodes.items() if p.startswith(prefix)]

    def parm(self, name):
        template = self._type.templates.get(name)
        return FakeParm(template) if template is not None else None

    def setCurrent(self, on, clear_all_selected=False):
        self.world.log.append(("setCurrent", self._path))
        if clear_all_selected:
            for n in self.world.nodes.values():
                n.selected = False
        self.current = on
        self.selected = on

    def setSelected(self, on, clear_all_selected=False):
        self.selected = on


class FakeEditor:
    def __init__(self, world, pwd):
        self.world = world
        self._pwd = pwd
        self.shown = 0
        self.homed = 0
        self.flashes: list[str] = []
        self.current_node = None

    def pwd(self): return self.world.nodes[self._pwd]

    def setPwd(self, node):
        self.world.log.append(("setPwd", node.path()))
        self._pwd = node.path()

    def setCurrentNode(self, node):
        self.world.log.append(("editor.setCurrentNode", node.path()))
        self.current_node = node

    def homeToSelection(self): self.homed += 1
    def setIsCurrentTab(self): self.shown += 1
    def flashMessage(self, image, message, duration): self.flashes.append(message)


class FakePane:
    def __init__(self, pinned=False):
        self.shown = 0
        self.pinned = pinned

    def setIsCurrentTab(self): self.shown += 1
    def isPin(self): return self.pinned

    def setPin(self, on):
        self.pinned = bool(on)


def make_world(paths: dict, pwd: str = "/obj", with_spreadsheet: bool = True, parm_pinned: bool = False,
               templates: dict | None = None):
    """paths: {ノードのパス: タイプ名（または (タイプ名, 表示名)）}。/ と /obj は自動で足す。
    templates: {タイプ名: [FakeTemplate, ...]}"""
    world = types.SimpleNamespace(nodes={}, log=[])
    templates = templates or {}

    def add(path, spec):
        type_name, label = spec if isinstance(spec, tuple) else (spec, "")
        world.nodes[path] = FakeNode(world, path, type_name, label, templates.get(type_name, ()))

    add("/", "root")
    add("/obj", "obj")
    for path, spec in paths.items():
        parts = path.strip("/").split("/")
        for i in range(1, len(parts)):
            parent = "/" + "/".join(parts[:i])
            if parent not in world.nodes:
                add(parent, "subnet")
        add(path, spec)
    editor = FakeEditor(world, pwd)
    parm, viewer, sheet = FakePane(pinned=parm_pinned), FakePane(), FakePane()
    tabs = {"NetworkEditor": editor, "Parm": parm, "SceneViewer": viewer}
    pane_types = {name: name for name in tabs}
    if with_spreadsheet:
        tabs["DetailsViewer"] = sheet
        pane_types["DetailsViewer"] = "DetailsViewer"

    categories = {}
    for node in world.nodes.values():
        categories.setdefault(node.type().category().name(), {})[node.type().name()] = node.type()
    category_objs = {
        name: types.SimpleNamespace(name=(lambda n=name: n), nodeTypes=(lambda d=d: d)) for name, d in categories.items()
    }
    helped: list = []
    hou = types.SimpleNamespace(
        paneTabType=types.SimpleNamespace(**pane_types),
        ui=types.SimpleNamespace(paneTabOfType=lambda t: tabs.get(t), displayNodeHelp=lambda nt: helped.append(nt)),
        node=lambda path: world.nodes.get(path),
        selectedNodes=lambda: [n for n in world.nodes.values() if n.selected],
        nodeTypeCategories=lambda: category_objs,
    )
    world.hou = hou
    world.editor, world.parm, world.viewer, world.sheet, world.helped = editor, parm, viewer, sheet, helped
    return world
