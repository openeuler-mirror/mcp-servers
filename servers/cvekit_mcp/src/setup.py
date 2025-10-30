from setuptools import setup, find_packages

setup(
    name="cvekit",
    version="1.0.0",
    description="CVE analysis and management toolkit",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "tabulate",
    ],
    scripts=["bin/cvekit"],
    entry_points={
        'console_scripts': [
            'cvekit = cvekit.cli:main',
        ],
    },
)