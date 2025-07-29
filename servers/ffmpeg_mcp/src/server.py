import subprocess
import shlex
import json
import os
import signal
from typing import Dict, List
from mcp.server.fastmcp import FastMCP

def handle_exception(exc_type, exc_value, exc_traceback):
    if exc_type == KeyboardInterrupt:
        print("\nServer stopped by user")
    else:
        print(f"Server error: {str(exc_value)}")

mcp = FastMCP("FFmpeg 媒体处理工具")
# 设置全局异常处理
signal.signal(signal.SIGINT, lambda s, f: handle_exception(KeyboardInterrupt, None, None))

@mcp.tool()
def probe_video(input_file: str) -> dict:
    """获取视频文件信息"""
    try:
        cmd = f"ffprobe -v quiet -print_format json -show_format -show_streams {input_file}"
        result = subprocess.check_output(
            shlex.split(cmd),
            text=True,
            stderr=subprocess.STDOUT
        )
        return {"status": "success", "data": json.loads(result)}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def convert_to_mp4(input_file: str, output_file: str) -> dict:
    """转换视频到MP4格式(H.264/AAC)"""
    try:
        cmd = f"ffmpeg -i {input_file} -c:v libx264 -c:a aac {output_file}"
        subprocess.check_output(
            shlex.split(cmd),
            text=True,
            stderr=subprocess.STDOUT
        )
        return {"status": "success", "output_file": output_file}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool() 
def convert_to_webm(input_file: str, output_file: str) -> dict:
    """转换视频到WebM格式"""
    try:
        cmd = f"ffmpeg -i {input_file} {output_file}"
        subprocess.check_output(
            shlex.split(cmd),
            text=True,
            stderr=subprocess.STDOUT
        )
        return {"status": "success", "output_file": output_file}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def extract_aac(input_file: str, output_file: str) -> dict:
    """提取AAC音频流"""
    try:
        cmd = f"ffmpeg -i {input_file} -vn -c:a copy {output_file}"
        subprocess.check_output(
            shlex.split(cmd),
            text=True,
            stderr=subprocess.STDOUT
        )
        return {"status": "success", "output_file": output_file}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def extract_mp3(input_file: str, output_file: str) -> dict:
    """提取MP3音频"""
    try:
        cmd = f"ffmpeg -i {input_file} -q:a 0 -map a {output_file}"
        subprocess.check_output(
            shlex.split(cmd),
            text=True,
            stderr=subprocess.STDOUT
        )
        return {"status": "success", "output_file": output_file}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def remove_audio(input_file: str, output_file: str) -> dict:
    """移除视频中的音频"""
    try:
        cmd = f"ffmpeg -i {input_file} -c copy -an {output_file}"
        subprocess.check_output(
            shlex.split(cmd),
            text=True,
            stderr=subprocess.STDOUT
        )
        return {"status": "success", "output_file": output_file}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def merge_av(video_file: str, audio_file: str, output_file: str) -> dict:
    """合并视频和音频"""
    try:
        cmd = f"ffmpeg -i {video_file} -i {audio_file} -c copy -shortest {output_file}"
        subprocess.check_output(
            shlex.split(cmd),
            text=True,
            stderr=subprocess.STDOUT
        )
        return {"status": "success", "output_file": output_file}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    mcp.run()