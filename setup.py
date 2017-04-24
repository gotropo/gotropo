from setuptools import setup, find_packages

setup(
    name='create_cloudformation',
    version='0.1',
    py_modules=['create_cloudformation'],
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
