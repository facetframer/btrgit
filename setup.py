import setuptools
import os

HERE = os.path.dirname(__file__)

setuptools.setup(
    name='btrgit',
    version="0.1.0",
    author='Tal Wrii',
    author_email='facetframer@gmail.com',
    description='',
    license='GPLv3',
    keywords='',
    url='',
    packages=['btrgit'],
    long_description='See https://github.com/facetframer/btrgit',
    entry_points={
        'console_scripts': ['btrgit=btrgit.btrgit:main']
    },
    classifiers=[
        "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)"
    ],
    test_suite='nose.collector',
    install_requires=[]
)
