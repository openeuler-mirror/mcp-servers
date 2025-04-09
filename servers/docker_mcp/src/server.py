import subprocess
import shlex
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("用来执行docker相关命令")

@mcp.tool()
def get_docker_image() -> dict:
    """统计当前机器上的docker镜像有哪些"""
    try:
        # 执行docker image命令并返回
        result = subprocess.check_output(['sudo', 'docker', 'images'], 
                                        text=True, 
                                        stderr=subprocess.STDOUT)
        
        return result
    except subprocess.CalledProcessError as e:
        return e
    except Exception as e:
        return e

@mcp.tool()
def get_docker_list() -> dict:
    """统计当前机器上已有哪些容器"""
    try:
        # 执行docker ps令并返回
        result = subprocess.check_output(['sudo', 'docker', 'ps', '-a'], 
                                        text=True, 
                                        stderr=subprocess.STDOUT)
        
        return result
    except subprocess.CalledProcessError as e:
        return e
    except Exception as e:
        return e

@mcp.tool()
def run_docker(docker_image:str, docker_env=None,flexible_para=None) -> dict:
    """
    运行一个容器
    Args:
    docker_image:容器镜像名称
    docker_env:容器运行需要的环境变量，格式为：ENV_EXAMPLE=xxx,需要根据容器镜像灵活添加,默认为空
    flexible_para:容器运行时需要的其他参数，可以根据容器镜像要求与用户要求灵活添加，用户不指定就不要添加，保证参数最少，不要添加-d
    """
    cmd = ['sudo', 'docker','run']
    if docker_env:
        cmd = cmd + ["-e", docker_env]
    if flexible_para:
        processed_list=[]
        processed_list.extend(shlex.split(flexible_para))
        cmd.extend(processed_list)

    cmd = cmd + ['-d', docker_image]
    try:
        # 运行某一个容器
        result = subprocess.check_output(cmd, 
                                        text=True, 
                                        stderr=subprocess.STDOUT)
        
        return f"创建成功，容器ID：{result}"
    except subprocess.CalledProcessError as e:
        return e
    except Exception as e:
        return e

@mcp.tool()
def delete_docker(docker_id_list:list) -> dict:
    """
    批量删除容器
    Args:
    docker_id_list:容器id列表，一个id为一个元素
    """
    success_result = []
    failed_result = []
    for docker_id in docker_id_list:
        try:
            # 删除某一个容器，并返回结果
            result = subprocess.check_output(['sudo', 'docker', "rm","-f", docker_id], 
                                            text=True, 
                                            stderr=subprocess.STDOUT)
        
            success_result.append(docker_id)
        except subprocess.CalledProcessError as e:
            failed_result.append(docker_id)
        except Exception as e:
            failed_result.append(docker_id)
    
    return f"执行成功的容器：{success_result}，失败的容器：{failed_result}"
    

@mcp.tool()
def manage_docker(action:str, docker_id_list:list) -> dict:
    """
    容器批量管理，包括启动，停止，重启
    Args:
    action:动作，启动：start，停止：stop，重启：restart
    docker_id_list:容器id列表，一个id为一个元素
    """
    success_result = []
    failed_result = []
    for docker_id in docker_id_list:
        try:
            # 操作某一个容器，并返回结果
            result = subprocess.check_output(['sudo', 'docker', action, docker_id], 
                                            text=True, 
                                            stderr=subprocess.STDOUT)
        
            success_result.append(docker_id)
        except subprocess.CalledProcessError as e:
            failed_result.append(docker_id)
        except Exception as e:
            failed_result.append(docker_id)
    
    return f"执行成功的容器：{success_result}，失败的容器：{failed_result}"
    

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run()
