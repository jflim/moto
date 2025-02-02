import boto3

from moto import mock_aws


@mock_aws
def test_create_without_tags():
    client = boto3.client("es", region_name="us-east-1")
    arn = client.create_elastic_domain(DomainName="testdn")["DomainStatus"]["ARN"]

    assert client.list_tags(ARN=arn)["TagList"] == []


@mock_aws
def test_create_with_tags():
    client = boto3.client("es", region_name="us-east-1")
    domain = client.create_elastic_domain(
        DomainName="testdn", TagList=[{"Key": "k1", "Value": "v1"}]
    )
    arn = domain["DomainStatus"]["ARN"]

    assert client.list_tags(ARN=arn)["TagList"] == [{"Key": "k1", "Value": "v1"}]

    client.add_tags(ARN=arn, TagList=[{"Key": "k2", "Value": "v2"}])

    assert client.list_tags(ARN=arn)["TagList"] == [
        {"Key": "k1", "Value": "v1"},
        {"Key": "k2", "Value": "v2"},
    ]

    client.remove_tags(ARN=arn, TagKeys=["k1"])

    assert client.list_tags(ARN=arn)["TagList"] == [{"Key": "k2", "Value": "v2"}]


@mock_aws
def test_add_tags():
    client = boto3.client("es", region_name="us-east-1")
    domain = client.create_elastic_domain(DomainName="testdn")

    arn = domain["DomainStatus"]["ARN"]

    client.add_tags(ARN=arn, TagList=[{"Key": "k1", "Value": "v1"}, {"Key": "k2", "Value": "v2"}])

    assert client.list_tags(ARN=arn)["TagList"] == [
        {"Key": "k1", "Value": "v1"},
        {"Key": "k2", "Value": "v2"},
    ]

    assert client.list_tags(ARN=arn)["TagList"] == [{"Key": "k2", "Value": "v2"}]

@mock_aws
def test_add_duplicate_tags():
    client = boto3.client("es", region_name="us-east-1")
    domain = client.create_elastic_domain(
        DomainName="testdn", TagList=[{"Key": "k1", "Value": "v1"}]
    )
    arn = domain["DomainStatus"]["ARN"]

    assert client.list_tags(ARN=arn)["TagList"] == [{"Key": "k1", "Value": "v1"}]

    client.add_tags(ARN=arn, TagList=[{"Key": "k1", "Value": "v2"}])

    assert client.list_tags(ARN=arn)["TagList"] == [
        {"Key": "k1", "Value": "v1"},
        {"Key": "k2", "Value": "v2"},
    ]


@mock_aws
def test_remove_tags():
    client = boto3.client("es", region_name="us-east-1")
    domain = client.create_elastic_domain(
        DomainName="testdn", TagList=[{"Key": "k1", "Value": "v1"}]
    )
    arn = domain["DomainStatus"]["ARN"]

    assert client.list_tags(ARN=arn)["TagList"] == [{"Key": "k1", "Value": "v1"}]

    response = client.remove_tags(ARN=arn, TagKeys=['k1'])


    assert client.list_tags(ARN=arn)["TagList"] == []