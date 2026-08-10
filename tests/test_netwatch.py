import pytest
from deskbar.netwatch import classify_link_state

def test_classify_link_state():
    # wlan0:connected
    out1 = "wlan0:connected\np2p-dev-wlan0:disconnected\nlo:connected (externally)"
    assert classify_link_state(out1) == "connected"
    
    # progressing
    out2 = "wlan0:connecting (getting IP configuration)\np2p-dev-wlan0:disconnected"
    assert classify_link_state(out2) == "progressing"
    
    # dead
    out3 = "wlan0:disconnected\np2p-dev-wlan0:disconnected"
    assert classify_link_state(out3) == "dead"
    
    # unavailable
    out4 = "wlan0:unavailable\n"
    assert classify_link_state(out4) == "dead"
    
    # various progressing states
    for state in ["need-auth", "config", "prepare", "ip-config", "ip-check", "secondaries", "connecting"]:
        assert classify_link_state(f"wlan0:{state}") == "progressing"
        
    # empty string
    assert classify_link_state("") == "dead"
    
    # p2p-dev-wlan0 only
    assert classify_link_state("p2p-dev-wlan0:connected") == "dead"
    
    # eth0 / usb0
    assert classify_link_state("eth0:connected") == "connected"
    assert classify_link_state("usb0:connected") == "connected"
    
    # tailscale0 only
    assert classify_link_state("tailscale0:connected") == "dead"
