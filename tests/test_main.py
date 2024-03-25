import pytest
from pytouchline_extended import PyTouchline

def test_init():
    touchline = PyTouchline(id=1, url="http://192.168.1.254")
    assert touchline._id == 1
    assert touchline._url == "http://192.168.1.254"