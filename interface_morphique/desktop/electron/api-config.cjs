'use strict';

function resolveApiScheme({ packaged, configuredScheme }) {
  if (packaged) return 'https';
  return configuredScheme === 'https' ? 'https' : 'http';
}

module.exports = { resolveApiScheme };
