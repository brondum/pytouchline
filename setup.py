from setuptools import setup
setup(
  name = 'pytouchline_extended',
  packages = ['pytouchline'],
  version = '0.3',
  description = 'A Roth Touchline interface library',
  author = 'Peter Brondum',
  license='MIT',
  url = 'https://github.com/brondum/pytouchline',
  download_url = 'https://github.com/brondum/pytouchline/archive/0.3.tar.gz',
  keywords = ['Roth', 'Touchline', 'Home Assistant', 'hassio', "Heat pump"],
  classifiers = [
	'Development Status :: 3 - Alpha',
	'Intended Audience :: Developers',
	'License :: OSI Approved :: MIT License',
	'Programming Language :: Python :: 3',
  ],
  install_requires=['httplib2', 'faust-cchardet']
)