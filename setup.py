from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="bank-region-query",
    version="1.2.0",
    author="Yurui Hong",
    author_email="yuruihong02@outlook.com",
    description="A tool to query bank region codes",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/YuruiHong/bank-region-query",
    packages=find_packages(include=['bank_region_query', 'bank_region_query.*']),  # Fixed: include all subpackages
    package_data={
        "bank_region_query": ["data/*.json"],
    },
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Database",
    ],
    python_requires=">=3.7",
    install_requires=[],
    extras_require={
        "dev": ["pytest>=6.0", "pytest-cov", "black", "flake8"],
    },
    entry_points={
        "console_scripts": [
            "bank-query=bank_region_query.cli:main",
        ],
    },
)
