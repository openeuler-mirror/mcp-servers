import subprocess
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Package Dependency Analyzer")

def run_command(cmd):
    try:
        result = subprocess.run(cmd, check=True, 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE,
                              text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"

def parse_rpm_dependencies(output):
    # Parse rpm -qR output into dependency tree
    dependencies = [line.strip() for line in output.split('\n') if line.strip()]
    return {"dependencies": dependencies}

def parse_dnf_dependencies(output):
    # Parse dnf repoquery --requires output
    dependencies = [line.strip() for line in output.split('\n') if line.strip()]
    return {"dependencies": dependencies}

def parse_pip_dependencies(output):
    # Parse pip show output
    dep_info = {}
    for line in output.split('\n'):
        if 'Requires:' in line:
            deps = line.split(':')[1].strip().split(', ')
            dep_info["dependencies"] = [d for d in deps if d]
    return dep_info

@mcp.tool()
def analyze_rpm_dependencies(package_name: str, recursive: bool = True) -> str:
    """Analyze RPM package dependencies"""
    cmd = ["rpm", "-qR", package_name]
    output = run_command(cmd)
    result = parse_rpm_dependencies(output)
    return json.dumps(result, indent=2)

@mcp.tool()
def analyze_dnf_dependencies(package_name: str) -> str:
    """Analyze DNF package dependencies"""
    cmd = ["dnf", "repoquery", "--requires", package_name]
    output = run_command(cmd)
    result = parse_dnf_dependencies(output)
    return json.dumps(result, indent=2)

@mcp.tool()
def analyze_pip_dependencies(package_name: str) -> str:
    """Analyze Python pip package dependencies"""
    cmd = ["pip", "show", package_name]
    output = run_command(cmd)
    result = parse_pip_dependencies(output)
    return json.dumps(result, indent=2)

def parse_npm_dependencies(output):
    """Parse npm ls --json output into dependency tree"""
    try:
        data = json.loads(output)
        return {
            "dependencies": list(data.get("dependencies", {}).keys()),
            "version": data.get("version", "")
        }
    except json.JSONDecodeError:
        return {"error": "Invalid JSON output from npm"}

def parse_yarn_dependencies(output):
    """Parse yarn list --json output into dependency tree"""
    try:
        data = json.loads(output)
        return {
            "dependencies": [dep.split("@")[0] for dep in data.get("data", {}).get("trees", [])],
            "version": data.get("data", {}).get("version", "")
        }
    except json.JSONDecodeError:
        return {"error": "Invalid JSON output from yarn"}

def parse_pnpm_dependencies(output):
    """Parse pnpm list --json output into dependency tree"""
    try:
        data = json.loads(output)
        return {
            "dependencies": list(data.get("dependencies", {}).keys()),
            "version": data.get("version", "")
        }
    except json.JSONDecodeError:
        return {"error": "Invalid JSON output from pnpm"}

@mcp.tool()
def analyze_npm_dependencies(package_name: str) -> str:
    """Analyze NPM package dependencies"""
    cmd = ["npm", "ls", package_name, "--json"]
    output = run_command(cmd)
    result = parse_npm_dependencies(output)
    return json.dumps(result, indent=2)

@mcp.tool()
def analyze_yarn_dependencies(package_name: str) -> str:
    """Analyze Yarn package dependencies"""
    cmd = ["yarn", "list", "--pattern", package_name, "--json"]
    output = run_command(cmd)
    result = parse_yarn_dependencies(output)
    return json.dumps(result, indent=2)

@mcp.tool()
def analyze_pnpm_dependencies(package_name: str) -> str:
    """Analyze PNPM package dependencies"""
    cmd = ["pnpm", "list", package_name, "--json"]
    output = run_command(cmd)
    result = parse_pnpm_dependencies(output)
    return json.dumps(result, indent=2)

if __name__ == "__main__":
    mcp.run()