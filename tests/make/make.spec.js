const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { parse } = require('dotenv');

const rootPath = path.join(__dirname, '..', '..');
const envPath = path.join(rootPath, '.env');

function clearEnv() {
  fs.rmSync(envPath, { force: true });
}

function runSetup(env) {
  clearEnv();
  const result = spawnSync('make', ['setup'], {
    env: { ...process.env, ...env },
    encoding: 'utf-8',
  });
  if (result.stderr) {
    throw new Error(result.stderr);
  }
  return parse(fs.readFileSync(envPath, { encoding: 'utf-8' }));
}

function getConfig(env = {}) {
  const rawEnv = runSetup(env);
  const { stdout: rawConfig, stderr: rawError } = spawnSync(
    'docker',
    ['compose', 'config', '--format', 'json'],
    {
      encoding: 'utf-8',
      env: { ...process.env, ...env },
    },
  );
  try {
    if (rawError) throw new Error(rawError);
    return JSON.parse(rawConfig);
  } catch (error) {
    throw new Error(
      JSON.stringify({ error, rawConfig, rawError, rawEnv }, null, 2),
    );
  }
}

describe('docker-compose.yml', () => {
  afterAll(() => {
    clearEnv();
  });

  describe.each([
    ['development', 'development'],
    ['development', 'production'],
    ['production', 'development'],
    ['production', 'production'],
  ])('DOCKER_TARGET=%s, OLYMPIA_MOUNT=%s', (DOCKER_TARGET, OLYMPIA_MOUNT) => {
    const isProdTarget = DOCKER_TARGET === 'production';
    const isProdMount = OLYMPIA_MOUNT === 'production';
    const isProdMountTarget = isProdMount && isProdTarget;

    const inputValues = {
      DOCKER_TARGET,
      OLYMPIA_MOUNT,
      DOCKER_TAG: 'mozilla/addons-server:tag',
      DEBUG: 'debug',
      DATA_BACKUP_SKIP: 'skip',
    };

    it('.services.(web|worker) should have the correct configuration', () => {
      const {
        services: { web, worker },
      } = getConfig(inputValues);

      for (let service of [web, worker]) {
        expect(service.image).toStrictEqual(inputValues.DOCKER_TAG);
        expect(service.pull_policy).toStrictEqual('never');
        expect(service.user).toStrictEqual('root');
        expect(service.platform).toStrictEqual('linux/amd64');
        expect(service.entrypoint).toStrictEqual([
          '/data/olympia/docker/entrypoint.sh',
        ]);
        expect(service.extra_hosts).toStrictEqual(['olympia.test=127.0.0.1']);
        expect(service.restart).toStrictEqual('on-failure:5');
        // Each service should have a healthcheck
        expect(service.healthcheck).toHaveProperty('test');
        expect(service.healthcheck.interval).toStrictEqual('30s');
        expect(service.healthcheck.retries).toStrictEqual(3);
        expect(service.healthcheck.start_interval).toStrictEqual('1s');
        // each service should have a command
        expect(service.command).not.toBeUndefined();
        // each service should have the same dependencies
        expect(service.depends_on).toEqual(
          expect.objectContaining({
            autograph: expect.any(Object),
            elasticsearch: expect.any(Object),
            memcached: expect.any(Object),
            mysqld: expect.any(Object),
            rabbitmq: expect.any(Object),
            redis: expect.any(Object),
          }),
        );
        expect(service.volumes).toEqual(
          expect.arrayContaining([
            expect.objectContaining({
              source: isProdMountTarget ? 'data_olympia_' : expect.any(String),
              target: '/data/olympia',
            }),
            expect.objectContaining({
              source: isProdMountTarget
                ? 'data_olympia_storage'
                : expect.any(String),
              target: '/data/olympia/storage',
            }),
          ]),
        );
        const { OLYMPIA_MOUNT, ...environmentOutput } = inputValues;
        expect(service.environment).toEqual(
          expect.objectContaining({
            ...environmentOutput,
          }),
        );
        // We excpect not to pass the input values to the container
        expect(service.environment).not.toHaveProperty('OLYMPIA_UID');
      }

      expect(web.volumes).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            source: 'data_static_build',
            target: '/data/olympia/static-build',
          }),
          expect.objectContaining({
            source: 'data_site_static',
            target: '/data/olympia/site-static',
          }),
        ]),
      );
    });

    it('.services.nginx should have the correct configuration', () => {
      const {
        services: { nginx },
      } = getConfig(inputValues);
      // nginx is mapped from http://olympia.test to port 80 in /etc/hosts on the host
      expect(nginx.ports).toStrictEqual([
        expect.objectContaining({
          mode: 'ingress',
          protocol: 'tcp',
          published: '80',
          target: 80,
        }),
      ]);
      expect(nginx.volumes).toEqual(
        expect.arrayContaining([
          // mapping for nginx conf.d adding addon-server routing
          expect.objectContaining({
            source: 'data_nginx',
            target: '/etc/nginx/conf.d',
          }),
          // mapping for local host directory to /data/olympia
          expect.objectContaining({
            source: isProdMountTarget ? 'data_olympia_' : expect.any(String),
            target: '/srv',
          }),
          expect.objectContaining({
            source: 'data_site_static',
            target: '/srv/site-static',
          }),
          // mapping for local host directory to /data/olympia/storage
          expect.objectContaining({
            source: isProdMountTarget
              ? 'data_olympia_storage'
              : expect.any(String),
            target: '/srv/storage',
          }),
        ]),
      );
    });

    it('.services.*.volumes duplicate volumes should be defined on services.olympia_volumes.volumes', () => {
      const key = 'olympia_volumes';
      const { services } = getConfig(inputValues);
      // all volumes defined on any service other than olympia
      const volumesMap = new Map();
      // volumes defined on the olympia service, any dupes in other services should be here also
      const olympiaVolumes = new Set();

      for (let [name, config] of Object.entries(services)) {
        for (let volume of config.volumes ?? []) {
          if (volume.bind) continue;
          const source = volume.source || volume.target;

          if (name === key) {
            olympiaVolumes.add(source);
          } else {
            const set = volumesMap.get(source) ?? new Set();
            volumesMap.set(source, set.add(name));
          }
        }
      }

      // duplicate volumes should be defined on the olympia service
      // to ensure that the volume is mounted by docker before any
      // other service tries to use it.
      for (let [source, services] of volumesMap) {
        if (services.size > 1 && !olympiaVolumes.has(source)) {
          const serviceNames = [...services].join(', ');
          throw new Error(
            `.services.${key}.volumes missing '${source}' used by '${serviceNames}'`,
          );
        }
      }

      // any service that depends on a duplicate volume must also depend on olympia
      for (let source of olympiaVolumes) {
        for (let name of volumesMap.get(source) ?? []) {
          if (!services[name]?.depends_on?.[key]) {
            throw new Error(
              `'.services.${name}.depends_on' missing '${key}' for shared volume '${source}'`,
            );
          }
        }
      }
    });

    it('.services.*.volumes does not contain anonymous or unnamed volumes', () => {
      const { services } = getConfig(inputValues);
      for (let [name, config] of Object.entries(services)) {
        for (let volume of config.volumes ?? []) {
          if (!volume.bind && !volume.source) {
            throw new Error(
              `'.services.${name}.volumes' contains unnamed volume mount: ` +
                `'${volume.target}'. Please use a named volume mount instead.`,
            );
          }
        }
      }
    });

    const EXCLUDED_KEYS = ['DOCKER_COMMIT', 'DOCKER_VERSION', 'DOCKER_BUILD'];
    // This test ensures that we do NOT include environment variables that are used
    // at build time in the container. Cointainer environment variables are dynamic
    // and should not be able to deviate from the state at build time.
    it('.services.(web|worker).environment excludes build info variables', () => {
      const {
        services: { web, worker },
      } = getConfig({
        ...inputValues,
        ...Object.fromEntries(EXCLUDED_KEYS.map((key) => [key, 'filtered'])),
      });
      for (let service of [web, worker]) {
        for (let key of EXCLUDED_KEYS) {
          expect(service.environment).not.toHaveProperty(key);
        }
      }
    });
  });

  // these keys require special handling to prevent runtime errors in make setup
  const failKeys = [
    // Invalid docker tag leads to docker not parsing the image
    'DOCKER_TAG',
    // Value is read directly as the volume source for /data/olympia and must be valid
    'HOST_MOUNT_SOURCE',
  ];
  const ignoreKeys = [
    // Ignored because these values are explicitly mapped to the host_* values
    'OLYMPIA_UID',
    'OLYMPIA_MOUNT',
    // Ignored because the HOST_UID is always set to the host user's UID
    'HOST_UID',
    'HOST_MOUNT',
  ];
  const defaultEnv = runSetup();
  const customValue = 'custom';

  describe.each(Array.from(new Set([...Object.keys(defaultEnv), ...failKeys])))(
    `custom value for environment variable %s=${customValue}`,
    (key) => {
      if (failKeys.includes(key)) {
        it('config should fail if set to an arbitrary custom value', () => {
          expect(() =>
            getConfig({ DOCKER_TARGET: 'production', [key]: customValue }),
          ).toThrow();
        });
      } else if (ignoreKeys.includes(key)) {
        it('variable should be ignored', () => {
          const {
            services: { web, worker },
          } = getConfig({ ...defaultEnv, [key]: customValue });
          for (let service of [web, worker]) {
            expect(service.environment).not.toEqual(
              expect.objectContaining({
                [key]: customValue,
              }),
            );
          }
        });
      } else {
        it('variable should be overriden based on the input', () => {
          const {
            services: { web, worker },
          } = getConfig({ ...defaultEnv, [key]: customValue });
          for (let service of [web, worker]) {
            expect(service.environment).toEqual(
              expect.objectContaining({
                [key]: customValue,
              }),
            );
          }
        });
      }
    },
  );
});

describe('docker-bake.hcl', () => {
  afterAll(() => {
    clearEnv();
  });

  function getBakeConfig(env = {}) {
    runSetup(env);
    const { stdout: output } = spawnSync(
      'make',
      ['docker_build_web', 'ARGS=--print'],
      {
        encoding: 'utf-8',
        env: { ...process.env, ...env },
      },
    );

    return output;
  }
  it('renders empty values for undefined variables', () => {
    const output = getBakeConfig();
    expect(output).toContain('"DOCKER_BUILD": ""');
    expect(output).toContain('"DOCKER_COMMIT": ""');
    expect(output).toContain('"DOCKER_VERSION": ""');
    expect(output).toContain('"target": "development"');
    expect(output).toContain('mozilla/addons-server:local');
  });

  it('renders custom DOCKER_BUILD', () => {
    const build = 'build';
    const output = getBakeConfig({ DOCKER_BUILD: build });
    expect(output).toContain(`"DOCKER_BUILD": "${build}"`);
  });

  it('renders custom DOCKER_COMMIT', () => {
    const commit = 'commit';
    const output = getBakeConfig({ DOCKER_COMMIT: commit });
    expect(output).toContain(`"DOCKER_COMMIT": "${commit}"`);
  });

  it('renders custom DOCKER_VERSION', () => {
    const version = 'version';
    const output = getBakeConfig({ DOCKER_VERSION: version });
    expect(output).toContain(`"DOCKER_VERSION": "${version}"`);
    expect(output).toContain(`mozilla/addons-server:${version}`);
  });

  it('renders custom DOCKER_DIGEST', () => {
    const digest = 'sha256:digest';
    const output = getBakeConfig({ DOCKER_DIGEST: digest });
    expect(output).toContain(`mozilla/addons-server@${digest}`);
  });

  it('renders custom target', () => {
    const target = 'target';
    const output = getBakeConfig({ DOCKER_TARGET: target });
    expect(output).toContain(`"target": "${target}"`);
  });
});
