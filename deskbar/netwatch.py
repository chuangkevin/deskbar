"""
純函數化的網路狀態判定。
shell 難測，把判定邏輯用可測的純函數釘住規格，shell 那邊照同一份規則實作。
2026-08-07 事故中，因為 shell 版誤把正在重連的中間狀態當成死線，導致 1758 次 radio 重啟，引發 3 天斷線。
"""

import re

def classify_link_state(nmcli_output: str) -> str:
    """
    從 nmcli -t -f DEVICE,STATE dev 的輸出判定三態。
    回傳 "connected" / "progressing" / "dead"。純函數、不做 I/O。
    """
    lines = nmcli_output.strip().splitlines()
    has_progressing = False
    
    valid_prefix = re.compile(r'^(wlan0|usb[0-9]*|eth[0-9]*):')
    progressing_states = ('connecting', 'prepare', 'config', 'need-auth', 'ip-config', 'ip-check', 'secondaries')
    
    for line in lines:
        if not valid_prefix.match(line):
            continue
            
        parts = line.split(':', 1)
        if len(parts) != 2:
            continue
            
        state = parts[1]
        
        if state == 'connected':
            return 'connected'
            
        if any(state.startswith(s) for s in progressing_states):
            has_progressing = True
            
    if has_progressing:
        return 'progressing'
        
    return 'dead'
