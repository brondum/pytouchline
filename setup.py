from setuptools import setup
setup(
  name = 'pytouchline_extended',
  packages = ['pytouchline_extended'],
  version = '0.0.0',
  description = 'A Roth Touchline interface library',
  long_description="A simple helper library for controlling a Roth Touchline heat pump controller",
  author = 'Peter Brondum',
  license='MIT',
  url = 'https://github.com/brondum/pytouchline',
  keywords = ['Roth', 'Touchline', 'Home Assistant', 'hassio', "Heat pump"],
  classifiers = [
	'Development Status :: 3 - Alpha',
	'Intended Audience :: Developers',
	'License :: OSI Approved :: MIT License',
	'Programming Language :: Python :: 3',
  ],
  install_requires=['httplib2', 'faust-cchardet']
)