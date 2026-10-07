from distutils.core import setup

from utils import __version__

setup(
    name="telegram-media-downloader-enhanced",
    version=__version__,
    author="ack528",
    author_email="82737603+ack528@users.noreply.github.com",
    description="Enhanced Telegram media downloader for reliable long-running tasks",
    url="https://github.com/ack528/telegram_media_downloader_enhanced",
    download_url=(
        "https://github.com/ack528/telegram_media_downloader_enhanced/"
        "releases/latest"
    ),
    py_modules=["media_downloader"],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Operating System :: OS Independent",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet",
        "Topic :: Communications",
        "Topic :: Communications :: Chat",
        "Topic :: Software Development :: Libraries",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    project_urls={
        "Tracker": (
            "https://github.com/ack528/telegram_media_downloader_enhanced/issues"
        ),
        "Community": (
            "https://github.com/ack528/telegram_media_downloader_enhanced/"
            "discussions"
        ),
        "Source": "https://github.com/ack528/telegram_media_downloader_enhanced",
    },
    python_requires="~=3.7",
)
