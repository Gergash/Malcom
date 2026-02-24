from mcp.server.fastmcp import FastMCP
import subprocess
import sys
import os
import pandas as pd
import pickle

mcp = FastMCP("insightflow")


@mcp.tool()
def hello(name: str = "world") -> str:
    """Say hello. Optional name to greet."""
    return f"Hello, {name}!"


@mcp.tool()
def run_script(script_path: str) -> str:
    """Run any python script"""
    
    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=True,
        text=True
    )
    
    return result.stdout or result.stderr


@mcp.tool()
def list_data_files() -> list:
    """List files in data folder"""
    
    if os.path.exists("data"):
        return os.listdir("data")
    
    return []


@mcp.tool()
def load_model(model_path: str) -> str:
    """Load pickle model"""
    
    if os.path.exists(model_path):
        return "Model ready"
    
    return "Model not found"


if __name__ == "__main__":
    mcp.run()