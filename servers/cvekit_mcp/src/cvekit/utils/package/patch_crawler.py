#!/usr/bin/python3
"""
软件包CVE patch爬虫 - 复用cve_tracking项目
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import namedtuple

logger = logging.getLogger(__name__)

class PackagePatchCrawler:
    """
    软件包CVE patch爬虫 - 复用cve_tracking项目
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化爬虫
        
        Args:
            config_path: 配置文件路径，如果为None则使用默认配置
        """
        self.config_path = config_path
        self._init_cve_tracking_components()
        logger.info("PackagePatchCrawler初始化完成")
    
    def _init_cve_tracking_components(self):
        """初始化cve_tracking的组件"""
        try:
            from core.crawler.patch import Patch
            from conf import settings
            from constant import Constant
        except ImportError as exc:
            raise ImportError("cve_tracking模块不可用，请检查路径和依赖") from exc
        
        # 复用数据结构
        self._SummaryInfo = namedtuple("SummaryInfo", ["pr_list", "issues_list"])
        self._PatchDetail = namedtuple("PatchDetail", ["platform", "details"])
        self._Patch = Patch
        # 复用配置
        self.settings = settings
        self.constants = Constant
        
        # 存储中间结果
        self.patch_info_list = []
        self.patch_detail_list = []
        self.issue_pr_dict = {}
        self.pr_status_dict = {}
    
    async def get_package_commits(self, cve_id: str, package_name: str) -> Tuple[List[Dict], List[Dict]]:
        """
        获取软件包CVE相关的commits
        
        Args:
            cve_id: CVE编号，如 "CVE-2025-58186"
            package_name: 软件包名称，如 "ceph"
            
        Returns:
            Tuple[List[Dict], List[Dict]]: (commits列表, patch详情列表)
        """
        logger.info(f"开始获取CVE {cve_id} 软件包 {package_name} 的commit信息")
        
        try:
            # 1. 使用复用的Patch类
            patch_crawler = self._Patch(cve_num=cve_id, rpm_name=package_name)
            
            # 2. 复用find_patches_detail方法
            patch_details = await patch_crawler.find_patches_detail()
            self.patch_detail_list = patch_details
            
            # 3. 提取commits
            commits = self._extract_commits_from_patch_details(patch_details)
            
            # 4. 获取commit详细信息
            detailed_commits = await self._enrich_commits(commits)
            
            logger.info(f"成功获取到 {len(detailed_commits)} 个commits")
            return detailed_commits, patch_details
            
        except Exception as e:
            logger.error(f"获取commit信息失败: {str(e)}")
            raise
    
    def _extract_commits_from_patch_details(self, patch_details: List) -> List[Dict]:
        """
        从patch_details中提取commits
        
        Args:
            patch_details: cve_tracking返回的补丁详情
            
        Returns:
            List[Dict]: 简化的commit信息
        """
        commits = []
        
        for patch_detail in patch_details:
            platform = patch_detail.get("platform", "unknown")
            details = patch_detail.get("details", [])
            
            for detail in details:
                if "issue" in detail:
                    issue_info = detail["issue"]
                    prs = issue_info.get("prs", [])
                    
                    for pr in prs:
                        pr_commits = pr.get("commits", [])
                        for commit_url in pr_commits:
                            commits.append({
                                "url": commit_url,
                                "platform": platform,
                                "type": "pr_commit",
                                "pr_url": pr.get("url"),
                                "pr_status": pr.get("status"),
                                "source": "cve_tracking"
                            })
        return commits
    
    async def _enrich_commits(self, commits: List[Dict]) -> List[Dict]:
        """
        丰富commit的详细信息
        
        Args:
            commits: 基础commit信息
            
        Returns:
            List[Dict]: 详细的commit信息
        """
        detailed_commits = []
        
        for commit in commits:
            # 提取commit hash
            commit_hash = self._extract_commit_hash(commit["url"])
            
            detailed_commit = {
                **commit,
                "hash": commit_hash,
                "extracted_at": datetime.now().isoformat(timespec="seconds"),
            }
            detailed_commits.append(detailed_commit)
        dedup_commits = list({c["hash"]: c for c in detailed_commits if "hash" in c}.values())
        return dedup_commits
    
    def _extract_commit_hash(self, url: str) -> Optional[str]:
        """
        从commit URL中提取hash
        """
        import re
        
        patterns = [
            r'/commit/([0-9a-f]{40})',
            r'/\?id=([0-9a-f]{40})',
            r'/commit/([0-9a-f]{8,40})',
            r'/rev/([0-9a-f]{8,40})',
            r'/ci/([0-9a-f]{8,40})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
