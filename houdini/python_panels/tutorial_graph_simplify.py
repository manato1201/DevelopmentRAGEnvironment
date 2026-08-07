"""
tutorial_graph_simplify.py — NodeGraphAsset（nodes/edges）の簡略化ロジック。

houdini_tools.export_node_graph() が出力する NodeGraphAsset 形式:
    node: {"id", "kind", "label", "position": [x, y], "params": {...}, "parent"?}
    edge: {"source", "target", "sourceOutput"?, "targetInput"?}

生成されたチュートリアルは Houdini の内部補助ノードまで含めて100〜200ノード規模に
なりやすく、そのまま QGraphicsScene に描画すると判読不能な塊になる（tutorial_view.py
の _NodeGraphScene が抱えていた問題）。ここでは「入力が1つ・出力が1つの
ノードが分岐なく連続している区間（直列チェーン）」を1つの集約ノードへ折り畳む
アルゴリズムと、その結果を Mermaid の flowchart テキストへ変換する関数を提供する。

このモジュールは PySide6 等の GUI ライブラリに一切依存しない（Houdini 本体や
Qt が無い環境でも import してユニットテストできる）。tutorial_view.py はこの
モジュールの関数を使って QGraphicsScene 用のノード/エッジリストを作る。
"""

from __future__ import annotations

import re
from collections import deque

__all__ = ["simplify_graph", "graph_to_mermaid", "layered_positions"]


def simplify_graph(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    直列チェーン（分岐・合流の無い一本道）を1つの集約ノードに折り畳む。

    「線形ノード」= 入力辺・出力辺がそれぞれ0本または1本（すなわち分岐も合流もしない）
    かつ、他ノードの parent として参照されるコンテナ（サブネット等）ではないノード。
    分岐点（出力2本以上）・合流点（入力2本以上）・サブネット境界は線形ノードの
    集合から除外されるため、折り畳みには一切巻き込まれず、常に個別ノードとして
    グラフに残る（隣が線形ノードであっても、そこで鎖は途切れる）。

    線形ノード同士を結ぶ辺（かつ parent が同一）だけを鎖として連結し、2ノード以上
    連なった鎖を1つの集約ノード（kind="chain"、id="chain::<先頭>->...->  <末尾>"、
    label は "id1 → id2 → id3（3ノード）" の形）にまとめる。1ノードだけの鎖（＝
    折り畳み相手がいない線形ノード）はそのまま個別ノードとして出力される。

    例: grid1(in=0,out=1) → mountain1(in=1,out=1) → scatter1(in=1,out=0) は
    3ノードとも線形ノードなので1つの集約ノードに折り畳まれる。
    一方 split1（出力2本の分岐点）や merge1（入力2本の合流点）は線形ノードでは
    ないため、隣接する線形ノードがあっても折り畳みに参加せず個別ノードのまま残る。

    戻り値: (簡略化後の nodes, 簡略化後の edges)。元の nodes/edges は変更しない。
    集約ノードには元の構成ノード辞書を "members" キーに保持する（詳細表示用）。
    """
    node_by_id = {n["id"]: n for n in nodes if "id" in n}
    node_ids = set(node_by_id.keys())

    out_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    for e in edges:
        src, dst = e.get("source"), e.get("target")
        if src in node_ids:
            out_degree[src] += 1
        if dst in node_ids:
            in_degree[dst] += 1

    # 他ノードの parent として参照されているノード = サブネット等のコンテナ。
    # コンテナは常に個別ノードとして残す（線形ノード集合から除外する）。
    container_ids = {
        n.get("parent") for n in nodes if n.get("parent") in node_ids
    }

    # 線形ノード: 分岐（out>=2）も合流（in>=2）もせず、コンテナでもないノード。
    linear = {
        nid for nid in node_ids
        if in_degree[nid] <= 1 and out_degree[nid] <= 1 and nid not in container_ids
    }

    # 線形ノード同士を繋ぐ辺だけを鎖として連結する。u, v が両方 linear であれば
    # out_degree(u)<=1 かつ辺 u->v が存在する以上 out_degree(u)==1 が確定し、
    # 同様に in_degree(v)==1 も確定するので、chain_next/chain_prev の代入は
    # 高々1回ずつしか起こらず競合しない。
    chain_next: dict[str, str] = {}
    chain_prev: dict[str, str] = {}
    for e in edges:
        u, v = e.get("source"), e.get("target")
        if u not in linear or v not in linear:
            continue
        if node_by_id[u].get("parent") != node_by_id[v].get("parent"):
            continue  # 別サブネットを跨いで折り畳まない
        chain_next[u] = v
        chain_prev[v] = u

    # チェーンの先頭（chain_prev を持たない = 誰からも折り畳まれてこない線形ノード）
    # から chain_next を辿って連なりを確定する。
    chains: list[list[str]] = []
    for n in nodes:
        nid = n.get("id")
        if nid is None or nid not in linear or nid in chain_prev:
            continue  # 先頭ではない、または線形ノードでない
        run = [nid]
        seen_in_run = {nid}
        cur = nid
        while cur in chain_next:
            nxt = chain_next[cur]
            if nxt in seen_in_run:
                break  # 循環防止（通常のノードグラフでは発生しないはずの安全策）
            run.append(nxt)
            seen_in_run.add(nxt)
            cur = nxt
        chains.append(run)

    # id -> 集約後の代表ノードid（折り畳まれなければ元のidのまま）
    rep: dict[str, str] = {}
    agg_nodes: list[dict] = []
    for run in chains:
        if len(run) < 2:
            continue  # 折り畳み相手がいない線形ノードは個別ノードのまま
        agg_id = "chain::" + "->".join(run)
        labels = [node_by_id[i].get("label") or i for i in run]
        head = node_by_id[run[0]]
        agg_nodes.append({
            "id": agg_id,
            "kind": "chain",
            "label": " → ".join(labels) + f"（{len(run)}ノード）",
            "position": head.get("position", [0, 0]),
            "parent": head.get("parent"),
            "members": [node_by_id[i] for i in run],
        })
        for i in run:
            rep[i] = agg_id

    new_nodes: list[dict] = list(agg_nodes)
    for n in nodes:
        if n.get("id") not in rep:
            new_nodes.append(n)

    seen_edges: set[tuple[str, str]] = set()
    new_edges: list[dict] = []
    for e in edges:
        u, v = e.get("source"), e.get("target")
        if u not in node_ids or v not in node_ids:
            continue
        ru, rv = rep.get(u, u), rep.get(v, v)
        if ru == rv:
            continue  # チェーン内部の辺は集約ノードに吸収されるので出力しない
        key = (ru, rv)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        new_edges.append({**e, "source": ru, "target": rv})

    return new_nodes, new_edges


def _topo_order(ids: list[str], parents: dict[str, list[str]]) -> list[str]:
    """
    Kahn法によるトポロジカルソート。サイクルが混入していても（通常のノード
    グラフでは起きないはずだが安全策として）取りこぼしたノードは末尾に
    そのままの順序で追加し、例外を出さずに常に何らかの順序を返す。
    """
    children: dict[str, list[str]] = {i: [] for i in ids}
    in_degree: dict[str, int] = {i: len(parents.get(i, [])) for i in ids}
    for nid in ids:
        for p in parents.get(nid, []):
            children.setdefault(p, []).append(nid)

    queue = deque(sorted(i for i in ids if in_degree[i] == 0))
    order: list[str] = []
    remaining_in_degree = dict(in_degree)
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for child in children.get(nid, []):
            remaining_in_degree[child] -= 1
            if remaining_in_degree[child] == 0:
                queue.append(child)

    seen = set(order)
    order.extend(i for i in ids if i not in seen)
    return order


def layered_positions(nodes: list[dict], edges: list[dict]) -> dict[str, tuple[float, float]]:
    """
    ノードグラフ（DAG）をパイプラインの向き（入力→出力）に沿った層（レイヤー）に
    配置する Sugiyama 風の簡易レイアウト。

    tutorial_view.py の旧実装は Houdini ネットワークエディタ上の生の座標
    （node["position"]）をそのままスケールして使っていたが、自動生成された
    グラフはノードが密集・重複しやすく（同じ位置に近いノードが多い、
    ノード同士が交差する等）、QGraphicsView にそのまま描画すると判読不能な
    塊になりやすい（実機で「グラフビューがひどい」と報告された不具合）。
    ここでは実際の座標を無視し、グラフの接続構造だけから配置を計算する。

    アルゴリズム:
      1. 各ノードの層番号 = 親（入力側）ノードからの最長経路長（トポロジカル順で計算）。
         入力を持たないノード（ソース）は層0。
      2. 同じ層の中では、親ノードの行位置の平均（barycenter）でソートすることで、
         エッジの交差をできるだけ減らす。
      3. 各層を中央揃えにする（行位置を層内ノード数の中心に合わせてシフト）ことで、
         上下にバラけた見た目ではなく左右対称な木/パイプライン図になる。

    戻り値: {node_id: (col, row)} の格子座標（呼び出し側でスケールをかけて
    シーン座標にする）。id を持たないノードは無視する。
    """
    ids = [n["id"] for n in nodes if "id" in n]
    id_set = set(ids)
    if not ids:
        return {}

    parents: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        u, v = e.get("source"), e.get("target")
        if u in id_set and v in id_set:
            parents[v].append(u)

    order = _topo_order(ids, parents)

    depth: dict[str, int] = {i: 0 for i in ids}
    for nid in order:
        for p in parents[nid]:
            depth[nid] = max(depth[nid], depth.get(p, 0) + 1)

    layers: dict[int, list[str]] = {}
    for nid in ids:
        layers.setdefault(depth[nid], []).append(nid)

    row: dict[str, float] = {}
    for d in sorted(layers):
        layer_nodes = layers[d]
        if d == 0:
            layer_nodes.sort()
        else:
            def _barycenter(nid: str) -> float:
                ps = parents[nid]
                return sum(row[p] for p in ps) / len(ps) if ps else 0.0

            layer_nodes.sort(key=_barycenter)
        # 中央揃え: 0..n-1 の行位置を、層の中心が0になるようシフトする
        offset = (len(layer_nodes) - 1) / 2.0
        for i, nid in enumerate(layer_nodes):
            row[nid] = i - offset

    return {nid: (float(depth[nid]), row[nid]) for nid in ids}


def _mermaid_id(node_id: str) -> str:
    """Mermaid のノードIDとして安全な文字列に変換する（英数字/アンダースコアのみ）。"""
    safe = re.sub(r"[^0-9A-Za-z_]", "_", str(node_id))
    if not safe or safe[0].isdigit():
        safe = "n_" + safe
    return safe


def _mermaid_label(label: str) -> str:
    """Mermaid のノードラベル内で問題になる文字（引用符・改行）をエスケープする。"""
    label = "" if label is None else str(label)
    label = label.replace('"', "'").replace("\n", " ").replace("\r", " ")
    return label


def graph_to_mermaid(nodes: list[dict], edges: list[dict], simplify: bool = True) -> str:
    """
    NodeGraphAsset の nodes/edges を Mermaid の `flowchart TD` テキストに変換する。

    simplify=True（既定）の場合、まず simplify_graph() でチェーン折り畳みを行った
    うえで出力する。Notion/Obsidian 等に貼って見やすく共有できるようにするための
    軽量な変換であり、PySide6 等のGUIライブラリには依存しない純粋関数。
    """
    if simplify:
        nodes, edges = simplify_graph(nodes, edges)

    lines = ["flowchart TD"]
    for n in nodes:
        nid = _mermaid_id(n.get("id"))
        label = _mermaid_label(n.get("label") or n.get("id") or "")
        kind = n.get("kind", "")
        if kind == "chain":
            lines.append(f'    {nid}["{label}"]')
        elif kind in ("subnet", "geo"):
            lines.append(f'    {nid}[["{label}"]]')
        else:
            lines.append(f'    {nid}("{label}")')

    for e in edges:
        if e.get("source") is None or e.get("target") is None:
            continue
        u = _mermaid_id(e["source"])
        v = _mermaid_id(e["target"])
        lines.append(f"    {u} --> {v}")

    return "\n".join(lines)
