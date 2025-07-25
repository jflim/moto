import random
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import ClientError

from moto import mock_aws, settings
from moto.core import DEFAULT_ACCOUNT_ID as ACCOUNT_ID
from moto.ec2.utils import random_private_ip
from tests import EXAMPLE_AMI_ID, aws_verified


@mock_aws
def test_elastic_network_interfaces():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    with pytest.raises(ClientError) as ex:
        ec2resource.create_network_interface(SubnetId=subnet.id, DryRun=True)
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412
    assert ex.value.response["Error"]["Code"] == "DryRunOperation"
    assert (
        ex.value.response["Error"]["Message"]
        == "An error occurred (DryRunOperation) when calling the CreateNetworkInterface operation: Request would have succeeded, but DryRun flag is set"
    )

    eni = ec2resource.create_network_interface(SubnetId=subnet.id)
    assert eni.availability_zone == subnet.availability_zone
    assert eni.subnet_id == subnet.id
    assert eni.vpc_id == vpc.id
    eni_id = eni.id

    my_enis = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])[
        "NetworkInterfaces"
    ]
    assert len(my_enis) == 1
    eni = my_enis[0]
    assert len(eni["Groups"]) == 1
    assert len(eni["PrivateIpAddresses"]) == 1
    assert eni["PrivateIpAddresses"][0]["PrivateIpAddress"].startswith("10.") is True

    with pytest.raises(ClientError) as ex:
        ec2client.delete_network_interface(NetworkInterfaceId=eni_id, DryRun=True)
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412
    assert ex.value.response["Error"]["Code"] == "DryRunOperation"
    assert (
        ex.value.response["Error"]["Message"]
        == "An error occurred (DryRunOperation) when calling the DeleteNetworkInterface operation: Request would have succeeded, but DryRun flag is set"
    )

    ec2client.delete_network_interface(NetworkInterfaceId=eni_id)

    all_enis = ec2client.describe_network_interfaces()["NetworkInterfaces"]
    assert eni_id not in [eni["NetworkInterfaceId"] for eni in all_enis]

    with pytest.raises(ClientError) as ex:
        ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert "RequestId" in ex.value.response["ResponseMetadata"]
    assert ex.value.response["Error"]["Code"] == "InvalidNetworkInterfaceID.NotFound"

    with pytest.raises(ClientError) as ex:
        ec2client.delete_network_interface(NetworkInterfaceId=eni_id)
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert "RequestId" in ex.value.response["ResponseMetadata"]
    assert ex.value.response["Error"]["Code"] == "InvalidNetworkInterfaceID.NotFound"


@mock_aws
def test_elastic_network_interfaces_subnet_validation():
    ec2client = boto3.client("ec2", "us-east-1")

    with pytest.raises(ClientError) as ex:
        ec2client.create_network_interface(SubnetId="subnet-abcd1234")
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert "RequestId" in ex.value.response["ResponseMetadata"]
    assert ex.value.response["Error"]["Code"] == "InvalidSubnetID.NotFound"


@mock_aws
def test_elastic_network_interfaces_with_private_ip():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    private_ip = "54.0.0.1"
    eni = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress=private_ip
    )

    all_enis = ec2client.describe_network_interfaces()["NetworkInterfaces"]
    assert eni.id in [eni["NetworkInterfaceId"] for eni in all_enis]

    my_enis = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])[
        "NetworkInterfaces"
    ]

    eni = my_enis[0]
    assert len(eni["Groups"]) == 1

    assert len(eni["PrivateIpAddresses"]) == 1
    assert eni["PrivateIpAddresses"][0]["PrivateIpAddress"] == private_ip


@mock_aws
def test_elastic_network_interfaces_with_groups():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    sec_group1 = ec2resource.create_security_group(
        GroupName=str(uuid4()), Description="n/a"
    )
    sec_group2 = ec2resource.create_security_group(
        GroupName=str(uuid4()), Description="n/a"
    )
    my_eni = subnet.create_network_interface(Groups=[sec_group1.id, sec_group2.id])

    all_enis = ec2client.describe_network_interfaces()["NetworkInterfaces"]
    assert my_eni.id in [eni["NetworkInterfaceId"] for eni in all_enis]

    my_eni_description = [
        eni for eni in all_enis if eni["NetworkInterfaceId"] == my_eni.id
    ][0]
    assert len(my_eni_description["Groups"]) == 2
    assert set([group["GroupId"] for group in my_eni_description["Groups"]]) == {
        sec_group1.id,
        sec_group2.id,
    }

    eni_groups_attribute = ec2client.describe_network_interface_attribute(
        NetworkInterfaceId=my_eni.id, Attribute="groupSet"
    ).get("Groups")

    assert len(eni_groups_attribute) == 2
    assert set([group["GroupId"] for group in eni_groups_attribute]) == {
        sec_group1.id,
        sec_group2.id,
    }


@mock_aws
def test_elastic_network_interfaces_without_group():
    # ENI should use the default SecurityGroup if not provided
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    my_eni = subnet.create_network_interface()

    all_enis = ec2client.describe_network_interfaces()["NetworkInterfaces"]
    assert my_eni.id in [eni["NetworkInterfaceId"] for eni in all_enis]

    my_eni = [eni for eni in all_enis if eni["NetworkInterfaceId"] == my_eni.id][0]
    assert len(my_eni["Groups"]) == 1
    assert my_eni["Groups"][0]["GroupName"] == "default"


@mock_aws
def test_elastic_network_interfaces_modify_attribute():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)
    sec_group1 = ec2resource.create_security_group(
        GroupName=str(uuid4()), Description="n/a"
    )
    sec_group2 = ec2resource.create_security_group(
        GroupName=str(uuid4()), Description="n/a"
    )
    eni_id = subnet.create_network_interface(Groups=[sec_group1.id]).id

    my_eni = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])[
        "NetworkInterfaces"
    ][0]

    assert len(my_eni["Groups"]) == 1
    assert my_eni["Groups"][0]["GroupId"] == sec_group1.id

    with pytest.raises(ClientError) as ex:
        ec2client.modify_network_interface_attribute(
            NetworkInterfaceId=eni_id, Groups=[sec_group2.id], DryRun=True
        )
    assert ex.value.response["Error"]["Code"] == "DryRunOperation"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412
    assert (
        ex.value.response["Error"]["Message"]
        == "An error occurred (DryRunOperation) when calling the ModifyNetworkInterfaceAttribute operation: Request would have succeeded, but DryRun flag is set"
    )

    ec2client.modify_network_interface_attribute(
        NetworkInterfaceId=eni_id, Groups=[sec_group2.id]
    )

    my_eni = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])[
        "NetworkInterfaces"
    ][0]
    assert len(my_eni["Groups"]) == 1
    assert my_eni["Groups"][0]["GroupId"] == sec_group2.id


@mock_aws
def test_elastic_network_interfaces_filtering():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    sec_group1 = ec2resource.create_security_group(
        GroupName=str(uuid4()), Description="n/a"
    )
    sec_group2 = ec2resource.create_security_group(
        GroupName=str(uuid4()), Description="n/a"
    )

    eni1 = subnet.create_network_interface(Groups=[sec_group1.id, sec_group2.id])
    eni2 = subnet.create_network_interface(Groups=[sec_group1.id])
    eni3 = subnet.create_network_interface(Description=str(uuid4()))

    all_enis = ec2client.describe_network_interfaces()["NetworkInterfaces"]
    assert eni1.id in [eni["NetworkInterfaceId"] for eni in all_enis]
    assert eni2.id in [eni["NetworkInterfaceId"] for eni in all_enis]
    assert eni3.id in [eni["NetworkInterfaceId"] for eni in all_enis]

    # Filter by NetworkInterfaceId
    enis_by_id = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni1.id])[
        "NetworkInterfaces"
    ]
    assert len(enis_by_id) == 1
    assert [eni["NetworkInterfaceId"] for eni in enis_by_id] == [eni1.id]

    # Filter by ENI ID
    enis_by_id = ec2client.describe_network_interfaces(
        Filters=[{"Name": "network-interface-id", "Values": [eni1.id]}]
    )["NetworkInterfaces"]
    assert len(enis_by_id) == 1
    assert [eni["NetworkInterfaceId"] for eni in enis_by_id] == [eni1.id]

    # Filter by Security Group
    enis_by_group = ec2client.describe_network_interfaces(
        Filters=[{"Name": "group-id", "Values": [sec_group1.id]}]
    )["NetworkInterfaces"]
    assert len(enis_by_group) == 2
    assert set([eni["NetworkInterfaceId"] for eni in enis_by_group]) == {
        eni1.id,
        eni2.id,
    }

    # Filter by ENI ID and Security Group
    enis_by_group = ec2client.describe_network_interfaces(
        Filters=[
            {"Name": "network-interface-id", "Values": [eni1.id]},
            {"Name": "group-id", "Values": [sec_group1.id]},
        ]
    )["NetworkInterfaces"]
    assert len(enis_by_group) == 1
    assert [eni["NetworkInterfaceId"] for eni in enis_by_group] == [eni1.id]

    # Filter by Description
    enis_by_description = ec2client.describe_network_interfaces(
        Filters=[{"Name": "description", "Values": [eni3.description]}]
    )["NetworkInterfaces"]
    assert len(enis_by_description) == 1
    assert enis_by_description[0]["Description"] == eni3.description

    # Unsupported filter
    if not settings.TEST_SERVER_MODE:
        # ServerMode will just throw a generic 500
        with pytest.raises(NotImplementedError):
            filters = [{"Name": "not-implemented-filter", "Values": ["foobar"]}]
            ec2client.describe_network_interfaces(Filters=filters)


@mock_aws
def test_elastic_network_interfaces_get_by_tag_name():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    eni1 = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress="10.0.10.5"
    )

    with pytest.raises(ClientError) as ex:
        eni1.create_tags(Tags=[{"Key": "Name", "Value": "eni1"}], DryRun=True)
    assert ex.value.response["Error"]["Code"] == "DryRunOperation"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412
    assert (
        ex.value.response["Error"]["Message"]
        == "An error occurred (DryRunOperation) when calling the CreateTags operation: Request would have succeeded, but DryRun flag is set"
    )

    tag_value = str(uuid4())
    eni1.create_tags(Tags=[{"Key": "Name", "Value": tag_value}])

    # The status of the new interface should be 'available'
    waiter = ec2client.get_waiter("network_interface_available")
    waiter.wait(NetworkInterfaceIds=[eni1.id])

    filters = [{"Name": "tag:Name", "Values": [tag_value]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 1

    filters = [{"Name": "tag:Name", "Values": ["wrong-name"]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 0


@mock_aws
def test_elastic_network_interfaces_get_by_availability_zone():
    ec2resource = boto3.resource("ec2", region_name="us-west-2")
    ec2client = boto3.client("ec2", region_name="us-west-2")

    vpc = ec2resource.create_vpc(CidrBlock="10.0.0.0/16")
    subnet1 = ec2resource.create_subnet(
        VpcId=vpc.id, CidrBlock="10.0.0.0/24", AvailabilityZone="us-west-2a"
    )

    subnet2 = ec2resource.create_subnet(
        VpcId=vpc.id, CidrBlock="10.0.1.0/24", AvailabilityZone="us-west-2b"
    )

    eni1 = ec2resource.create_network_interface(
        SubnetId=subnet1.id, PrivateIpAddress="10.0.0.15"
    )

    eni2 = ec2resource.create_network_interface(
        SubnetId=subnet2.id, PrivateIpAddress="10.0.1.15"
    )

    # The status of the new interface should be 'available'
    waiter = ec2client.get_waiter("network_interface_available")
    waiter.wait(NetworkInterfaceIds=[eni1.id, eni2.id])

    filters = [{"Name": "availability-zone", "Values": ["us-west-2a"]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert eni1.id in [eni.id for eni in enis]
    assert eni2.id not in [eni.id for eni in enis]

    filters = [{"Name": "availability-zone", "Values": ["us-west-2c"]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert eni1.id not in [eni.id for eni in enis]
    assert eni2.id not in [eni.id for eni in enis]


@mock_aws
def test_elastic_network_interfaces_get_by_private_ip():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)
    random_ip = ".".join(map(str, (random.randint(0, 99) for _ in range(4))))
    eni1 = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress=random_ip
    )

    # The status of the new interface should be 'available'
    waiter = ec2client.get_waiter("network_interface_available")
    waiter.wait(NetworkInterfaceIds=[eni1.id])

    filters = [{"Name": "private-ip-address", "Values": [random_ip]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 1

    filters = [{"Name": "private-ip-address", "Values": ["10.0.10.10"]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 0

    filters = [{"Name": "addresses.private-ip-address", "Values": [random_ip]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 1

    filters = [{"Name": "addresses.private-ip-address", "Values": ["10.0.10.10"]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 0


@mock_aws
def test_elastic_network_interfaces_get_by_vpc_id():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    eni1 = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress="10.0.10.5"
    )

    # The status of the new interface should be 'available'
    waiter = ec2client.get_waiter("network_interface_available")
    waiter.wait(NetworkInterfaceIds=[eni1.id])

    filters = [{"Name": "vpc-id", "Values": [subnet.vpc_id]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 1

    filters = [{"Name": "vpc-id", "Values": ["vpc-aaaa1111"]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 0


@mock_aws
def test_elastic_network_interfaces_get_by_subnet_id():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    eni1 = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress="10.0.10.5"
    )

    # The status of the new interface should be 'available'
    waiter = ec2client.get_waiter("network_interface_available")
    waiter.wait(NetworkInterfaceIds=[eni1.id])

    filters = [{"Name": "subnet-id", "Values": [subnet.id]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 1

    filters = [{"Name": "subnet-id", "Values": ["subnet-aaaa1111"]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 0


@mock_aws
def test_elastic_network_interfaces_get_by_description():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    desc = str(uuid4())
    eni1 = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress="10.0.10.5", Description=desc
    )

    # The status of the new interface should be 'available'
    waiter = ec2client.get_waiter("network_interface_available")
    waiter.wait(NetworkInterfaceIds=[eni1.id])

    filters = [{"Name": "description", "Values": [eni1.description]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 1

    filters = [{"Name": "description", "Values": ["bad description"]}]
    enis = list(ec2resource.network_interfaces.filter(Filters=filters))
    assert len(enis) == 0


@mock_aws
def test_elastic_network_interfaces_get_by_attachment_instance_id():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    security_group1 = ec2resource.create_security_group(
        GroupName=str(uuid4()), Description="desc"
    )

    create_instances_result = ec2resource.create_instances(
        ImageId=EXAMPLE_AMI_ID, MinCount=1, MaxCount=1
    )
    instance = create_instances_result[0]

    # we should have one ENI attached to our ec2 instance by default
    filters = [{"Name": "attachment.instance-id", "Values": [instance.id]}]
    enis = ec2client.describe_network_interfaces(Filters=filters)
    assert len(enis.get("NetworkInterfaces")) == 1

    # attach another ENI to our existing instance, total should be 2
    eni1 = ec2resource.create_network_interface(
        SubnetId=subnet.id, Groups=[security_group1.id]
    )
    ec2client.attach_network_interface(
        NetworkInterfaceId=eni1.id, InstanceId=instance.id, DeviceIndex=1
    )

    filters = [{"Name": "attachment.instance-id", "Values": [instance.id]}]
    enis = ec2client.describe_network_interfaces(Filters=filters)
    assert len(enis.get("NetworkInterfaces")) == 2

    # we shouldn't find any ENIs that are attached to this fake instance ID
    filters = [{"Name": "attachment.instance-id", "Values": ["this-doesnt-match-lol"]}]
    enis = ec2client.describe_network_interfaces(Filters=filters)
    assert len(enis.get("NetworkInterfaces")) == 0


@mock_aws
def test_elastic_network_interfaces_get_by_attachment_instance_owner_id():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    security_group1 = ec2resource.create_security_group(
        GroupName=str(uuid4()), Description="desc"
    )

    create_instances_result = ec2resource.create_instances(
        ImageId=EXAMPLE_AMI_ID, MinCount=1, MaxCount=1
    )
    instance = create_instances_result[0]

    eni1 = ec2resource.create_network_interface(
        SubnetId=subnet.id, Groups=[security_group1.id]
    )
    ec2client.attach_network_interface(
        NetworkInterfaceId=eni1.id, InstanceId=instance.id, DeviceIndex=1
    )

    filters = [{"Name": "attachment.instance-owner-id", "Values": [ACCOUNT_ID]}]
    enis = ec2client.describe_network_interfaces(Filters=filters)["NetworkInterfaces"]
    eni_ids = [eni["NetworkInterfaceId"] for eni in enis]
    assert eni1.id in eni_ids


@mock_aws
def test_elastic_network_interfaces_describe_network_interfaces_with_filter():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)
    random_ip = ".".join(map(str, (random.randint(0, 99) for _ in range(4))))

    sg = ec2client.create_security_group(Description="test", GroupName=str(uuid4()))
    sg_id = sg["GroupId"]

    eni1 = ec2resource.create_network_interface(
        SubnetId=subnet.id,
        PrivateIpAddress=random_ip,
        Description=str(uuid4()),
        Groups=[sg_id],
    )

    # The status of the new interface should be 'available'
    waiter = ec2client.get_waiter("network_interface_available")
    waiter.wait(NetworkInterfaceIds=[eni1.id])

    def assert_network_interface_found(resp):
        assert len(resp["NetworkInterfaces"]) >= 1
        for ni in resp["NetworkInterfaces"]:
            if eni1.id == ni["NetworkInterfaceId"]:
                break
        else:
            raise AssertionError("NetworkInterfaceId not found in response!")
        assert ni["NetworkInterfaceId"] == eni1.id
        assert ni["PrivateIpAddress"] == eni1.private_ip_address
        assert ni["Description"] == eni1.description

    # Filter by network-interface-id
    response = ec2client.describe_network_interfaces(
        Filters=[{"Name": "network-interface-id", "Values": [eni1.id]}]
    )
    assert_network_interface_found(response)

    # Filter by network-interface-id
    response = ec2client.describe_network_interfaces(
        Filters=[{"Name": "group-id", "Values": [sg_id]}]
    )
    assert_network_interface_found(response)

    response = ec2client.describe_network_interfaces(
        Filters=[{"Name": "network-interface-id", "Values": ["bad-id"]}]
    )
    assert len(response["NetworkInterfaces"]) == 0

    # Filter by private-ip-address
    response = ec2client.describe_network_interfaces(
        Filters=[{"Name": "private-ip-address", "Values": [eni1.private_ip_address]}]
    )
    assert_network_interface_found(response)

    response = ec2client.describe_network_interfaces(
        Filters=[{"Name": "private-ip-address", "Values": ["11.11.11.11"]}]
    )
    assert len(response["NetworkInterfaces"]) == 0

    # Filter by subnet-id
    response = ec2client.describe_network_interfaces(
        Filters=[{"Name": "subnet-id", "Values": [eni1.subnet.id]}]
    )
    assert_network_interface_found(response)

    response = ec2client.describe_network_interfaces(
        Filters=[{"Name": "subnet-id", "Values": ["sn-bad-id"]}]
    )
    assert len(response["NetworkInterfaces"]) == 0

    # Filter by description
    response = ec2client.describe_network_interfaces(
        Filters=[{"Name": "description", "Values": [eni1.description]}]
    )
    assert_network_interface_found(response)

    response = ec2client.describe_network_interfaces(
        Filters=[{"Name": "description", "Values": ["bad description"]}]
    )
    assert len(response["NetworkInterfaces"]) == 0

    # Filter by multiple filters
    response = ec2client.describe_network_interfaces(
        Filters=[
            {"Name": "private-ip-address", "Values": [eni1.private_ip_address]},
            {"Name": "network-interface-id", "Values": [eni1.id]},
            {"Name": "subnet-id", "Values": [eni1.subnet.id]},
        ]
    )
    assert_network_interface_found(response)


@mock_aws
def test_elastic_network_interfaces_filter_by_tag():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    dev_env = f"dev-{str(uuid4())[0:4]}"
    prod_env = f"prod-{str(uuid4())[0:4]}"

    eni_dev = ec2resource.create_network_interface(
        SubnetId=subnet.id,
        PrivateIpAddress="10.0.10.5",
        Description="dev interface",
        TagSpecifications=[
            {
                "ResourceType": "network-interface",
                "Tags": [{"Key": "environment", "Value": dev_env}],
            },
        ],
    )

    eni_prod = ec2resource.create_network_interface(
        SubnetId=subnet.id,
        PrivateIpAddress="10.0.10.6",
        Description="prod interface",
        TagSpecifications=[
            {
                "ResourceType": "network-interface",
                "Tags": [{"Key": "environment", "Value": prod_env}],
            },
        ],
    )

    for eni in [eni_dev, eni_prod]:
        waiter = ec2client.get_waiter("network_interface_available")
        waiter.wait(NetworkInterfaceIds=[eni.id])

    resp = ec2client.describe_network_interfaces(
        Filters=[{"Name": "tag:environment", "Values": ["staging"]}]
    )
    assert len(resp["NetworkInterfaces"]) == 0

    resp = ec2client.describe_network_interfaces(
        Filters=[{"Name": "tag:environment", "Values": [dev_env]}]
    )
    assert len(resp["NetworkInterfaces"]) == 1
    assert resp["NetworkInterfaces"][0]["Description"] == "dev interface"

    resp = ec2client.describe_network_interfaces(
        Filters=[{"Name": "tag:environment", "Values": [prod_env]}]
    )
    assert len(resp["NetworkInterfaces"]) == 1
    assert resp["NetworkInterfaces"][0]["Description"] == "prod interface"

    resp = ec2client.describe_network_interfaces(
        Filters=[{"Name": "tag:environment", "Values": [dev_env, prod_env]}]
    )
    assert len(resp["NetworkInterfaces"]) == 2


@mock_aws
def test_elastic_network_interfaces_auto_create_securitygroup():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    eni1 = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress="10.0.10.5", Groups=["testgroup"]
    )

    # The status of the new interface should be 'available'
    waiter = ec2client.get_waiter("network_interface_available")
    waiter.wait(NetworkInterfaceIds=[eni1.id])

    sgs = ec2client.describe_security_groups()["SecurityGroups"]
    found_sg = [sg for sg in sgs if sg["GroupId"] == "testgroup"]
    assert len(found_sg) == 1

    assert found_sg[0]["GroupName"] == "testgroup"
    assert found_sg[0]["Description"] == "testgroup"


@mock_aws
def test_assign_private_ip_addresses__by_address():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    primary_ip = "54.0.0.1"
    secondary_ip = "80.0.0.1"
    eni = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress=primary_ip
    )

    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    resp_eni = resp["NetworkInterfaces"][0]
    assert resp_eni["PrivateIpAddress"] == primary_ip
    assert resp_eni["PrivateIpAddresses"] == [
        {"Primary": True, "PrivateIpAddress": primary_ip}
    ]

    # Pass IP address to assign rather than SecondaryPrivateIpAddressCount.
    ec2client.assign_private_ip_addresses(
        NetworkInterfaceId=eni.id, PrivateIpAddresses=[secondary_ip]
    )

    # Verify secondary IP address is now present.
    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    resp_eni = resp["NetworkInterfaces"][0]
    assert resp_eni["PrivateIpAddress"] == primary_ip
    assert resp_eni["PrivateIpAddresses"] == [
        {"Primary": True, "PrivateIpAddress": primary_ip},
        {"Primary": False, "PrivateIpAddress": secondary_ip},
    ]

    # Assign the same IP address, this time via the ENI object.
    eni.assign_private_ip_addresses(PrivateIpAddresses=[secondary_ip])

    # Verify nothing changes.
    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    resp_eni = resp["NetworkInterfaces"][0]
    assert resp_eni["PrivateIpAddress"] == primary_ip
    assert resp_eni["PrivateIpAddresses"] == [
        {"Primary": True, "PrivateIpAddress": primary_ip},
        {"Primary": False, "PrivateIpAddress": secondary_ip},
    ]


@mock_aws
def test_assign_private_ip_addresses__with_secondary_count():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    private_ip = "54.0.0.1"
    eni = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress=private_ip
    )

    ec2client.assign_private_ip_addresses(
        NetworkInterfaceId=eni.id, SecondaryPrivateIpAddressCount=2
    )

    # Verify second ip's are added
    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    my_eni = resp["NetworkInterfaces"][0]

    assert my_eni["PrivateIpAddress"] == "54.0.0.1"
    assert len(my_eni["PrivateIpAddresses"]) == 3
    assert {"Primary": True, "PrivateIpAddress": "54.0.0.1"} in my_eni[
        "PrivateIpAddresses"
    ]

    # Not as ipv6 addresses though
    assert my_eni["Ipv6Addresses"] == []


@mock_aws
def test_unassign_private_ip_addresses():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    private_ip = "54.0.0.1"
    eni = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress=private_ip
    )

    ec2client.assign_private_ip_addresses(
        NetworkInterfaceId=eni.id, SecondaryPrivateIpAddressCount=2
    )
    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    my_eni = resp["NetworkInterfaces"][0]
    ips_before = [addr["PrivateIpAddress"] for addr in my_eni["PrivateIpAddresses"]]

    # Remove IP
    ec2client.unassign_private_ip_addresses(
        NetworkInterfaceId=eni.id, PrivateIpAddresses=[ips_before[1]]
    )

    # Verify it's gone
    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    my_eni = resp["NetworkInterfaces"][0]
    assert len(my_eni["PrivateIpAddresses"]) == 2
    assert {"Primary": True, "PrivateIpAddress": "54.0.0.1"} in my_eni[
        "PrivateIpAddresses"
    ]
    assert {"Primary": False, "PrivateIpAddress": ips_before[2]} in my_eni[
        "PrivateIpAddresses"
    ]


@mock_aws
def test_unassign_private_ip_addresses__multiple():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    private_ip = "54.0.0.1"
    eni = ec2resource.create_network_interface(
        SubnetId=subnet.id, PrivateIpAddress=private_ip
    )

    ec2client.assign_private_ip_addresses(
        NetworkInterfaceId=eni.id, SecondaryPrivateIpAddressCount=5
    )
    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    my_eni = resp["NetworkInterfaces"][0]
    ips_before = [addr["PrivateIpAddress"] for addr in my_eni["PrivateIpAddresses"]]

    # Remove IP
    ec2client.unassign_private_ip_addresses(
        NetworkInterfaceId=eni.id, PrivateIpAddresses=[ips_before[1], ips_before[2]]
    )

    # Verify it's gone
    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    my_eni = resp["NetworkInterfaces"][0]
    assert len(my_eni["PrivateIpAddresses"]) == 4
    assert {"Primary": True, "PrivateIpAddress": "54.0.0.1"} in my_eni[
        "PrivateIpAddresses"
    ]
    assert {"Primary": False, "PrivateIpAddress": ips_before[3]} in my_eni[
        "PrivateIpAddresses"
    ]
    assert {"Primary": False, "PrivateIpAddress": ips_before[4]} in my_eni[
        "PrivateIpAddresses"
    ]
    assert {"Primary": False, "PrivateIpAddress": ips_before[5]} in my_eni[
        "PrivateIpAddresses"
    ]


@mock_aws
def test_assign_ipv6_addresses__by_address():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    ipv6_orig = random_private_ip("2001:db8::/101", ipv6=True)
    ipv6_2 = random_private_ip("2001:db8::/101", ipv6=True)
    ipv6_3 = random_private_ip("2001:db8::/101", ipv6=True)
    eni = ec2resource.create_network_interface(
        SubnetId=subnet.id, Ipv6Addresses=[{"Ipv6Address": ipv6_orig}]
    )
    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    my_eni = resp["NetworkInterfaces"][0]
    assert my_eni["Ipv6Addresses"] == [{"Ipv6Address": ipv6_orig}]

    ec2client.assign_ipv6_addresses(
        NetworkInterfaceId=eni.id, Ipv6Addresses=[ipv6_2, ipv6_3]
    )

    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    my_eni = resp["NetworkInterfaces"][0]
    assert len(my_eni["Ipv6Addresses"]) == 3
    assert {"Ipv6Address": ipv6_orig} in my_eni["Ipv6Addresses"]
    assert {"Ipv6Address": ipv6_2} in my_eni["Ipv6Addresses"]
    assert {"Ipv6Address": ipv6_3} in my_eni["Ipv6Addresses"]


@mock_aws
def test_assign_ipv6_addresses__by_count():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    ipv6_orig = random_private_ip("2001:db8::/101", ipv6=True)
    eni = ec2resource.create_network_interface(
        SubnetId=subnet.id, Ipv6Addresses=[{"Ipv6Address": ipv6_orig}]
    )

    ec2client.assign_ipv6_addresses(NetworkInterfaceId=eni.id, Ipv6AddressCount=3)

    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    my_eni = resp["NetworkInterfaces"][0]
    assert len(my_eni["Ipv6Addresses"]) == 4
    assert {"Ipv6Address": ipv6_orig} in my_eni["Ipv6Addresses"]


@mock_aws
def test_assign_ipv6_addresses__by_address_and_count():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    ipv6_orig = random_private_ip("2001:db8::/101", ipv6=True)
    ipv6_2 = random_private_ip("2001:db8::/101", ipv6=True)
    ipv6_3 = random_private_ip("2001:db8::/101", ipv6=True)
    eni = ec2resource.create_network_interface(
        SubnetId=subnet.id, Ipv6Addresses=[{"Ipv6Address": ipv6_orig}]
    )

    ec2client.assign_ipv6_addresses(
        NetworkInterfaceId=eni.id, Ipv6Addresses=[ipv6_2, ipv6_3]
    )
    ec2client.assign_ipv6_addresses(NetworkInterfaceId=eni.id, Ipv6AddressCount=2)

    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    my_eni = resp["NetworkInterfaces"][0]
    assert len(my_eni["Ipv6Addresses"]) == 5
    assert {"Ipv6Address": ipv6_orig} in my_eni["Ipv6Addresses"]
    assert {"Ipv6Address": ipv6_2} in my_eni["Ipv6Addresses"]
    assert {"Ipv6Address": ipv6_3} in my_eni["Ipv6Addresses"]


@mock_aws
def test_unassign_ipv6_addresses():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)

    ipv6_orig = random_private_ip("2001:db8::/101", ipv6=True)
    ipv6_2 = random_private_ip("2001:db8::/101", ipv6=True)
    ipv6_3 = random_private_ip("2001:db8::/101", ipv6=True)
    eni = ec2resource.create_network_interface(
        SubnetId=subnet.id, Ipv6Addresses=[{"Ipv6Address": ipv6_orig}]
    )

    resp = ec2client.assign_ipv6_addresses(
        NetworkInterfaceId=eni.id, Ipv6Addresses=[ipv6_2, ipv6_3]
    )
    assert resp["AssignedIpv6Addresses"] == [ipv6_orig, ipv6_2, ipv6_3]

    resp = ec2client.unassign_ipv6_addresses(
        NetworkInterfaceId=eni.id, Ipv6Addresses=[ipv6_2]
    )
    assert resp["UnassignedIpv6Addresses"] == [ipv6_2]

    resp = ec2client.describe_network_interfaces(NetworkInterfaceIds=[eni.id])
    my_eni = resp["NetworkInterfaces"][0]
    assert len(my_eni["Ipv6Addresses"]) == 2
    assert {"Ipv6Address": ipv6_orig} in my_eni["Ipv6Addresses"]
    assert {"Ipv6Address": ipv6_3} in my_eni["Ipv6Addresses"]


@mock_aws
def test_elastic_network_interfaces_describe_attachment():
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)
    eni_id = subnet.create_network_interface(Description="A network interface").id
    instance_id = ec2client.run_instances(
        ImageId="ami-12c6146b", MinCount=1, MaxCount=1
    )["Instances"][0]["InstanceId"]

    ec2client.attach_network_interface(
        NetworkInterfaceId=eni_id, InstanceId=instance_id, DeviceIndex=1
    )

    my_eni_attachment = ec2client.describe_network_interface_attribute(
        NetworkInterfaceId=eni_id, Attribute="attachment"
    ).get("Attachment")
    assert my_eni_attachment["InstanceId"] == instance_id
    assert my_eni_attachment["DeleteOnTermination"] is False

    with pytest.raises(ClientError) as ex:
        ec2client.describe_network_interface_attribute(
            NetworkInterfaceId=eni_id, Attribute="attach"
        )
    assert ex.value.response["Error"]["Code"] == "InvalidParameterValue"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert (
        ex.value.response["Error"]["Message"]
        == "Value (attach) for parameter attribute is invalid. Unknown attribute."
    )

    with pytest.raises(ClientError) as ex:
        ec2client.describe_network_interface_attribute(
            NetworkInterfaceId=eni_id, Attribute="attachment", DryRun=True
        )
    assert ex.value.response["Error"]["Code"] == "DryRunOperation"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412
    assert (
        ex.value.response["Error"]["Message"]
        == "An error occurred (DryRunOperation) when calling the DescribeNetworkInterfaceAttribute operation: Request would have succeeded, but DryRun flag is set"
    )

    my_eni_description = ec2client.describe_network_interface_attribute(
        NetworkInterfaceId=eni_id, Attribute="description"
    ).get("Description")
    assert my_eni_description["Value"] == "A network interface"

    my_eni_source_dest_check = ec2client.describe_network_interface_attribute(
        NetworkInterfaceId=eni_id, Attribute="sourceDestCheck"
    ).get("SourceDestCheck")
    assert my_eni_source_dest_check["Value"] is True


@mock_aws
def test_eni_detachment():
    # Setup
    ec2resource, ec2client, vpc, subnet = setup_vpc(boto3)
    resp = ec2client.run_instances(ImageId="ami-12c6146b", MinCount=1, MaxCount=1)[
        "Instances"
    ][0]

    # Execute
    eni_id = resp["NetworkInterfaces"][0]["Attachment"]["AttachmentId"]
    with pytest.raises(ClientError) as ex:
        ec2client.detach_network_interface(AttachmentId=eni_id)

    # Verify
    assert ex.value.response["Error"]["Code"] == "OperationNotPermitted"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert (
        ex.value.response["Error"]["Message"]
        == "The network interface at device index 0 and networkCard index 0 cannot be detached."
    )


@aws_verified
@pytest.mark.aws_verified
@pytest.mark.parametrize(
    "delete_eni", [True, False], ids=["DeleteOnTermination", "KeepOnTermination"]
)
def test_create_instance__termination_deletes_eni(delete_eni):
    ssm = boto3.client("ssm", "us-east-1")
    kernel_61 = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
    ami_id = ssm.get_parameter(Name=kernel_61)["Parameter"]["Value"]

    ec2_client = boto3.client("ec2", "us-east-1")
    existing_subnet_id = ec2_client.describe_subnets()["Subnets"][0]["SubnetId"]

    instance = ec2_client.run_instances(
        MaxCount=1,
        MinCount=1,
        ImageId=ami_id,
        InstanceType="t3a.small",
        NetworkInterfaces=[
            {
                "DeleteOnTermination": delete_eni,
                "DeviceIndex": 0,
                "SubnetId": existing_subnet_id,
            }
        ],
    )["Instances"][0]
    instance_id = instance["InstanceId"]
    ec2_client.get_waiter("instance_running").wait(InstanceIds=[instance_id])

    eni_id = instance["NetworkInterfaces"][0]["NetworkInterfaceId"]
    eni = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])[
        "NetworkInterfaces"
    ][0]
    assert eni["Attachment"]["DeleteOnTermination"] is delete_eni

    ec2_client.terminate_instances(InstanceIds=[instance_id])
    ec2_client.get_waiter("instance_terminated").wait(InstanceIds=[instance_id])

    if delete_eni:
        with pytest.raises(ClientError) as exc:
            ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
        err = exc.value.response["Error"]
        assert err["Code"] == "InvalidNetworkInterfaceID.NotFound"
        assert err["Message"] == f"The networkInterface ID '{eni_id}' does not exist"
    else:
        # Still exists - let's manually delete
        ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])

        ec2_client.delete_network_interface(NetworkInterfaceId=eni_id)


@mock_aws
def test_recreate_instance_with_same_ip_address():
    ssm = boto3.client("ssm", "us-east-1")
    kernel_61 = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
    ami_id = ssm.get_parameter(Name=kernel_61)["Parameter"]["Value"]

    ec2_client = boto3.client("ec2", "us-east-1")
    existing_subnet_id = ec2_client.describe_subnets()["Subnets"][0]["SubnetId"]

    for _ in range(2):
        # Second attempt must not throw an exception about a used IP
        instance_id = ec2_client.run_instances(
            MaxCount=1,
            MinCount=1,
            ImageId=ami_id,
            InstanceType="t3a.small",
            NetworkInterfaces=[
                {
                    "PrivateIpAddress": "172.31.0.5",
                    "DeleteOnTermination": True,
                    "DeviceIndex": 0,
                    "SubnetId": existing_subnet_id,
                }
            ],
        )["Instances"][0]["InstanceId"]
        ec2_client.get_waiter("instance_running").wait(InstanceIds=[instance_id])

        ec2_client.terminate_instances(InstanceIds=[instance_id])
        ec2_client.get_waiter("instance_terminated").wait(InstanceIds=[instance_id])


def setup_vpc(boto3):
    ec2resource = boto3.resource("ec2", region_name="us-east-1")
    ec2client = boto3.client("ec2", "us-east-1")

    vpc = ec2resource.create_vpc(CidrBlock="10.0.0.0/16")
    subnet = ec2resource.create_subnet(
        VpcId=vpc.id, CidrBlock="10.0.0.0/18", Ipv6CidrBlock="2001:db8::/64"
    )
    return ec2resource, ec2client, vpc, subnet
