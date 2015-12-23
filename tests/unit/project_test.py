from __future__ import unicode_literals

import docker

from .. import mock
from .. import unittest
from compose.config.config import Config
from compose.config.types import VolumeFromSpec
from compose.const import LABEL_SERVICE
from compose.container import Container
from compose.project import Project
from compose.service import ContainerNet
from compose.service import Net
from compose.service import Service


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.mock_client = mock.create_autospec(docker.Client)

    def test_from_dict(self):
        project = Project.from_config('composetest', Config(None, [
            {
                'name': 'web',
                'image': 'busybox:latest'
            },
            {
                'name': 'db',
                'image': 'busybox:latest'
            },
        ], None), None)
        self.assertEqual(len(project.services), 2)
        self.assertEqual(project.get_service('web').name, 'web')
        self.assertEqual(project.get_service('web').options['image'], 'busybox:latest')
        self.assertEqual(project.get_service('db').name, 'db')
        self.assertEqual(project.get_service('db').options['image'], 'busybox:latest')

    def test_from_dict_sorts_in_dependency_order(self):
        project = Project.from_config('composetest', Config(None, [
            {
                'name': 'web',
                'image': 'busybox:latest',
                'links': ['db'],
            },
            {
                'name': 'db',
                'image': 'busybox:latest',
                'volumes_from': ['volume']
            },
            {
                'name': 'volume',
                'image': 'busybox:latest',
                'volumes': ['/tmp'],
            }
        ], None), None)

        self.assertEqual(project.services[0].name, 'volume')
        self.assertEqual(project.services[1].name, 'db')
        self.assertEqual(project.services[2].name, 'web')

    def test_from_config(self):
        dicts = Config(None, [
            {
                'name': 'web',
                'image': 'busybox:latest',
            },
            {
                'name': 'db',
                'image': 'busybox:latest',
            },
        ], None)
        project = Project.from_config('composetest', dicts, None)
        self.assertEqual(len(project.services), 2)
        self.assertEqual(project.get_service('web').name, 'web')
        self.assertEqual(project.get_service('web').options['image'], 'busybox:latest')
        self.assertEqual(project.get_service('db').name, 'db')
        self.assertEqual(project.get_service('db').options['image'], 'busybox:latest')

    def test_get_service(self):
        web = Service(
            project='composetest',
            name='web',
            client=None,
            image="busybox:latest",
        )
        project = Project('test', [web], None)
        self.assertEqual(project.get_service('web'), web)

    def test_get_services_returns_all_services_without_args(self):
        web = Service(
            project='composetest',
            name='web',
            image='foo',
        )
        console = Service(
            project='composetest',
            name='console',
            image='foo',
        )
        project = Project('test', [web, console], None)
        self.assertEqual(project.get_services(), [web, console])

    def test_get_services_returns_listed_services_with_args(self):
        web = Service(
            project='composetest',
            name='web',
            image='foo',
        )
        console = Service(
            project='composetest',
            name='console',
            image='foo',
        )
        project = Project('test', [web, console], None)
        self.assertEqual(project.get_services(['console']), [console])

    def test_get_services_with_include_links(self):
        db = Service(
            project='composetest',
            name='db',
            image='foo',
        )
        web = Service(
            project='composetest',
            name='web',
            image='foo',
            links=[(db, 'database')]
        )
        cache = Service(
            project='composetest',
            name='cache',
            image='foo'
        )
        console = Service(
            project='composetest',
            name='console',
            image='foo',
            links=[(web, 'web')]
        )
        project = Project('test', [web, db, cache, console], None)
        self.assertEqual(
            project.get_services(['console'], include_deps=True),
            [db, web, console]
        )

    def test_get_services_removes_duplicates_following_links(self):
        db = Service(
            project='composetest',
            name='db',
            image='foo',
        )
        web = Service(
            project='composetest',
            name='web',
            image='foo',
            links=[(db, 'database')]
        )
        project = Project('test', [web, db], None)
        self.assertEqual(
            project.get_services(['web', 'db'], include_deps=True),
            [db, web]
        )

    def test_use_volumes_from_container(self):
        container_id = 'aabbccddee'
        container_dict = dict(Name='aaa', Id=container_id)
        self.mock_client.inspect_container.return_value = container_dict
        project = Project.from_config('test', Config(None, [
            {
                'name': 'test',
                'image': 'busybox:latest',
                'volumes_from': [VolumeFromSpec('aaa', 'rw')]
            }
        ], None), self.mock_client)
        self.assertEqual(project.get_service('test')._get_volumes_from(), [container_id + ":rw"])

    def test_use_volumes_from_service_no_container(self):
        container_name = 'test_vol_1'
        self.mock_client.containers.return_value = [
            {
                "Name": container_name,
                "Names": [container_name],
                "Id": container_name,
                "Image": 'busybox:latest'
            }
        ]
        project = Project.from_config('test', Config(None, [
            {
                'name': 'vol',
                'image': 'busybox:latest'
            },
            {
                'name': 'test',
                'image': 'busybox:latest',
                'volumes_from': [VolumeFromSpec('vol', 'rw')]
            }
        ], None), self.mock_client)
        self.assertEqual(project.get_service('test')._get_volumes_from(), [container_name + ":rw"])

    def test_use_volumes_from_service_container(self):
        container_ids = ['aabbccddee', '12345']

        project = Project.from_config('test', Config(None, [
            {
                'name': 'vol',
                'image': 'busybox:latest'
            },
            {
                'name': 'test',
                'image': 'busybox:latest',
                'volumes_from': [VolumeFromSpec('vol', 'rw')]
            }
        ], None), None)
        with mock.patch.object(Service, 'containers') as mock_return:
            mock_return.return_value = [
                mock.Mock(id=container_id, spec=Container)
                for container_id in container_ids]
            self.assertEqual(
                project.get_service('test')._get_volumes_from(),
                [container_ids[0] + ':rw'])

    def test_net_unset(self):
        project = Project.from_config('test', Config(None, [
            {
                'name': 'test',
                'image': 'busybox:latest',
            }
        ], None), self.mock_client)
        service = project.get_service('test')
        self.assertEqual(service.net.id, None)
        self.assertNotIn('NetworkMode', service._get_container_host_config({}))

    def test_use_net_from_container(self):
        container_id = 'aabbccddee'
        container_dict = dict(Name='aaa', Id=container_id)
        self.mock_client.inspect_container.return_value = container_dict
        project = Project.from_config('test', Config(None, [
            {
                'name': 'test',
                'image': 'busybox:latest',
                'net': 'container:aaa'
            }
        ], None), self.mock_client)
        service = project.get_service('test')
        self.assertEqual(service.net.mode, 'container:' + container_id)

    def test_use_net_from_service(self):
        container_name = 'test_aaa_1'
        self.mock_client.containers.return_value = [
            {
                "Name": container_name,
                "Names": [container_name],
                "Id": container_name,
                "Image": 'busybox:latest'
            }
        ]
        project = Project.from_config('test', Config(None, [
            {
                'name': 'aaa',
                'image': 'busybox:latest'
            },
            {
                'name': 'test',
                'image': 'busybox:latest',
                'net': 'container:aaa'
            }
        ], None), self.mock_client)

        service = project.get_service('test')
        self.assertEqual(service.net.mode, 'container:' + container_name)

    def test_uses_default_network_true(self):
        web = Service('web', project='test', image="alpine", net=Net('test'))
        db = Service('web', project='test', image="alpine", net=Net('other'))
        project = Project('test', [web, db], None)
        assert project.uses_default_network()

    def test_uses_default_network_custom_name(self):
        web = Service('web', project='test', image="alpine", net=Net('other'))
        project = Project('test', [web], None)
        assert not project.uses_default_network()

    def test_uses_default_network_host(self):
        web = Service('web', project='test', image="alpine", net=Net('host'))
        project = Project('test', [web], None)
        assert not project.uses_default_network()

    def test_uses_default_network_container(self):
        container = mock.Mock(id='test')
        web = Service(
            'web',
            project='test',
            image="alpine",
            net=ContainerNet(container))
        project = Project('test', [web], None)
        assert not project.uses_default_network()

    def test_container_without_name(self):
        self.mock_client.containers.return_value = [
            {'Image': 'busybox:latest', 'Id': '1', 'Name': '1'},
            {'Image': 'busybox:latest', 'Id': '2', 'Name': None},
            {'Image': 'busybox:latest', 'Id': '3'},
        ]
        self.mock_client.inspect_container.return_value = {
            'Id': '1',
            'Config': {
                'Labels': {
                    LABEL_SERVICE: 'web',
                },
            },
        }
        project = Project.from_config(
            'test',
            Config(None, [{
                'name': 'web',
                'image': 'busybox:latest',
            }], None),
            self.mock_client,
        )
        self.assertEqual([c.id for c in project.containers()], ['1'])
