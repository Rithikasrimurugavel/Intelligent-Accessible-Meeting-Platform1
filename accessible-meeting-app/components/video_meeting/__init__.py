import os

import streamlit.components.v1 as components

_component = components.declare_component(
    "accessible_video_meeting", path=os.path.join(os.path.dirname(__file__), "frontend"))


def video_meeting(me: dict, peers: list, signals: list, ack: str, cfg: dict, ice_servers: list,
                  sentence_pause: float = 3.0, key: str = "video_meeting"):
    """
    Live video meeting tile grid (WebRTC mesh: video and audio go browser-to-browser).

    Returns the newest *batch* of events from the browser, or None:
        {"id": str, "sid": str, "events": [{"t": "hello"} | {"t": "sig", "to": sid, "data": {...}} |
                                           {"t": "caption", "text": str, "conf": float} |
                                           {"t": "sign", "words": [...], "conf": float}]}
    The browser sends the next batch only after `ack` equals the id of the previous one.
    """
    return _component(me=me, peers=peers, signals=signals, ack=ack, cfg=cfg, ice_servers=ice_servers,
                      sentence_pause=sentence_pause, key=key, default=None)
