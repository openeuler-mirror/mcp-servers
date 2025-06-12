import unittest
from unittest.mock import patch, MagicMock
import subprocess
import json
from oegitext_mcp import configure_oegitext, get_my_openeuler_issue, get_my_openeuler_project, get_my_openeuler_pr, create_openeuler_pr

class TestOeGitExtMCP(unittest.TestCase):
    
    @patch('subprocess.run')
    def test_configure_oegitext_success(self, mock_run):
        """测试token配置成功场景"""
        mock_run.return_value = MagicMock(returncode=0)
        configure_oegitext("test_token")
        mock_run.assert_called_once()
        
    @patch('subprocess.run')
    def test_configure_oegitext_failure(self, mock_run):
        """测试token配置失败场景"""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'cmd', b'error')
        with self.assertLogs(level='ERROR') as log:
            configure_oegitext("invalid_token")
        self.assertIn("Token配置失败", log.output[0])
    
    @patch('subprocess.run')
    @patch('builtins.print')
    def test_configure_oegitext_no_token(self, mock_print, mock_run):
        """测试未提供token场景（边界测试）"""
        configure_oegitext(None)
        mock_print.assert_called_with("未检测到token参数，请确保本地已预先配置")
        mock_run.assert_not_called()
    
    @patch('subprocess.check_output')
    def test_get_my_openeuler_issue_success(self, mock_output):
        """测试获取issue成功场景"""
        mock_output.return_value = json.dumps({"issues": []})
        result = get_my_openeuler_issue()
        self.assertIsInstance(result, str)
        self.assertEqual(result, '{"issues": []}')
        
    @patch('subprocess.check_output')
    def test_get_my_openeuler_issue_failure(self, mock_output):
        """测试获取issue失败场景"""
        mock_output.side_effect = subprocess.CalledProcessError(1, 'cmd', b'error')
        result = get_my_openeuler_issue()
        self.assertIsInstance(result, subprocess.CalledProcessError)
    
    @patch('oegitext_mcp.configure_oegitext')
    @patch('subprocess.check_output')
    def test_get_my_openeuler_project_success(self, mock_output, mock_configure):
        """测试获取项目成功场景"""
        mock_output.return_value = json.dumps({"projects": []})
        result = get_my_openeuler_project()
        mock_configure.assert_called_once()
        self.assertIsInstance(result, str)
        self.assertEqual(result, '{"projects": []}')
    
    @patch('oegitext_mcp.configure_oegitext')
    @patch('subprocess.check_output')
    def test_get_my_openeuler_project_failure(self, mock_output, mock_configure):
        """测试获取项目失败场景"""
        mock_output.side_effect = subprocess.CalledProcessError(1, 'cmd', b'error')
        result = get_my_openeuler_project()
        self.assertIn("error", result)
    
    @patch('subprocess.check_output')
    def test_get_my_openeuler_pr_success(self, mock_output):
        """测试获取PR成功场景"""
        mock_output.return_value = json.dumps({"prs": []})
        result = get_my_openeuler_pr("src-openeuler", "test-repo")
        self.assertIsInstance(result, str)
        self.assertEqual(result, '{"prs": []}')
    
    @patch('subprocess.check_output')
    def test_get_my_openeuler_pr_failure(self, mock_output):
        """测试获取PR失败场景"""
        mock_output.side_effect = subprocess.CalledProcessError(1, 'cmd', b'error')
        result = get_my_openeuler_pr("invalid", "repo")
        self.assertIsInstance(result, subprocess.CalledProcessError)
    
    @patch('subprocess.check_output')
    @patch('git.Repo')
    def test_create_openeuler_pr_success(self, mock_repo, mock_output):
        """测试创建PR成功场景（基本参数）"""
        # Mock Git 仓库信息
        mock_repo.return_value = MagicMock()
        mock_repo.return_value.remotes[0].url = "https://gitee.com/user/repo.git"
        mock_repo.return_value.active_branch.name = "dev"
        
        # Mock 子进程输出
        mock_output.return_value = "PR created"
        
        result = create_openeuler_pr(
            title="Test PR",
            source_namespace="test-user",
            source_repo_name="test-repo",
            source_branch="dev"
        )
        self.assertIn("result", result)
        self.assertEqual(result["result"], "PR created")
    
    @patch('subprocess.check_output')
    @patch('git.Repo')
    def test_create_openeuler_pr_with_combined_params(self, mock_repo, mock_output):
        """测试创建PR成功场景（组合参数）"""
        # Mock Git 仓库信息
        mock_repo.return_value = MagicMock()
        mock_repo.return_value.remotes[0].url = "https://gitee.com/user/repo.git"
        mock_repo.return_value.active_branch.name = "dev"
        
        # Mock 子进程输出
        mock_output.return_value = "PR created"
        
        result = create_openeuler_pr(
            title="Test PR",
            source_combined="test-user/repo:dev",
            target_combined="openeuler/repo:master"
        )
        self.assertIn("result", result)
        self.assertEqual(result["result"], "PR created")
    
    @patch('subprocess.check_output')
    @patch('oegitext_mcp.get_git_repo_info')
    def test_create_openeuler_pr_default_values(self, mock_get_git_repo_info, mock_output):
        """测试创建PR默认值设置场景"""
        # Mock 获取git仓库信息
        mock_get_git_repo_info.return_value = ("test-user", "repo", "dev")
        
        # Mock 子进程输出
        mock_output.return_value = "PR created"
        
        result = create_openeuler_pr(
            title="Test PR",
            source_namespace=None,
            source_repo_name=None,
            source_branch=None,
            target_namespace=None,
            target_repo_name=None,
            target_branch=None
        )
        
        # 检查结果
        self.assertIn("result", result)
        self.assertEqual(result["result"], "PR created")
        self.assertEqual(result["details"]["source_repo"], "test-user/repo")
        self.assertEqual(result["details"]["target_repo"], "openeuler/repo")
        self.assertEqual(result["details"]["source_branch"], "dev")
        self.assertEqual(result["details"]["target_branch"], "master")
    
    @patch('subprocess.check_output')
    def test_create_openeuler_pr_failure(self, mock_output):
        """测试创建PR失败场景（边界测试：空标题）"""
        mock_output.side_effect = subprocess.CalledProcessError(1, 'cmd', b'error')
        result = create_openeuler_pr(title="")
        self.assertIn("error", result)
    
    @patch('subprocess.check_output')
    def test_create_openeuler_pr_invalid_input(self, mock_output):
        """测试创建PR无效输入场景（边界测试：None值）"""
        mock_output.side_effect = subprocess.CalledProcessError(1, 'cmd', b'error')
        result = create_openeuler_pr(title=None)
        self.assertIn("error", result)

if __name__ == '__main__':
    unittest.main()