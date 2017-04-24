from setuptools import setup, find_packages

setup(
    name='go_tropo',
    version='0.1',
    py_modules=['go_tropo'],
    install_requires=[
        'boto3',
        'troposphere',
        'awacs',
        'PyYaml',
        'Click',
        'AWSLogs',
    ],
    entry_points='''
        [console_scripts]
        go-tropo=bin.go_tropo:go_tropo
    ''',
)
