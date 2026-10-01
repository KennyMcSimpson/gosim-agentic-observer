"""你的策略 · Your strategy — the only file you need to edit.

每次决策，平台把「现在可以观测的候选」按公开评分公式排好序交给你（第 1 个是估计收益最高的）。
你只需要决定：观测其中哪一个，或者这一时隙先等待。改完保存，先用公开场景本地复现分数，再把包含 `observer.project.json` 的完整项目提交到网站。

Each decision, the platform hands you the candidates that can legally be observed right now, already ranked
by the public scoring formula (index 0 = highest estimated gain). Decide which one to observe, or return None
to wait for this slot. Save, run the public scenarios locally, then submit the complete project (repository or ZIP) on the website.

Every candidate is a dict with these keys:
    tile_id, program (DARK / BRIGHT / BACKUP), request_id ("" when the exposure is not tied to a request),
    region_id, scheduling_class (REQUIRED / FLEXIBLE), nominal_exptime_seconds,
    combined_quality              current atmospheric x lunar quality for this tile (DARK >= 0.65, BRIGHT >= 0.40)
    estimated_science_score       expected science credit of the exposure
    terminal_penalty_avoidance    how much end-of-run penalty this exposure avoids (REQUIRED miss 1000, FLEXIBLE 100)
    request_policy_value          reward / avoided penalty of the observation request it serves
    estimated_total_gain          all of the above combined
    estimated_gain_per_second     estimated_total_gain / nominal_exptime_seconds  (the default ranking)

`snapshot` is the full decision snapshot (cursor, current_site_weather, active_requests, progress, night_start,
weekly ...) as documented on the platform's Docs page. `memory` is an empty dict at the start of each run that
you may fill with anything you want to remember between decisions (nothing else persists).

完整项目的入口、协议和本地练习步骤见仓库根目录的 `README.md`；平台规则与当前提交方式以官网 Docs/Rules 页面为准。
See the repository `README.md` for the complete-project entry, protocol, and local practice steps; the official Docs/Rules pages define the current submission flow.
"""


def choose_action(candidates, snapshot, memory):
    """Return the candidate dict to observe (you may set candidate["reason"]), or None to wait this slot."""
    if not candidates:
        return None  # nothing can be completed right now: waiting costs only 0.001 per second

    # --- Example ideas (uncomment / edit): ---------------------------------------------------------
    # 1. Never let a REQUIRED tile slip: prefer them whenever one is available.
    # required = [c for c in candidates if c["scheduling_class"] == "REQUIRED"]
    # if required:
    #     return required[0]
    #
    # 2. Serve observation requests first (they pay 140 per tile and cost 190 when missed).
    # for c in candidates:
    #     if c["request_id"]:
    #         return c
    #
    # 3. Skip poor conditions: wait unless the best candidate is at least BRIGHT quality.
    # if candidates[0]["combined_quality"] < 0.40:
    #     return None
    #
    # 4. Remember what you did: memory.setdefault("observed", []).append(candidates[0]["tile_id"])

    return candidates[0]  # default: the highest estimated gain per second
