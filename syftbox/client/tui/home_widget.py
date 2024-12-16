intro_md = """

# SyftBox

SyftBox is an innovative project by [OpenMined](https://openmined.org) that aims to make privacy-enhancing technologies (PETs) more accessible and user-friendly for developers.
It provides a modular and intuitive framework for building PETs applications with minimal barriers, regardless of the programming language or environment.

### Key Features

1. **A Network-First Architecture**: At its very foundation, SyftBox is architected as a distributed network system. Similar to modern file syncing platforms, it creates a seamless web of interconnected nodes called **Datasites**. Each Datasite acts as both a contributor and consumer within the network, sharing data and applications (known as APIs in SyftBox terminology) across the ecosystem. This network-centric architecture ensures efficient data distribution and collaboration while maintaining strict privacy boundaries, making SyftBox naturally suited for **Federated Learning** applications.

2. **Language and Environment Agnostic**: SyftBox is designed to be language and environment agnostic, allowing developers to use their preferred programming languages and tools. This flexibility ensures that a wide range of developers can leverage SyftBox's capabilities without having to learn new languages or switch development environments.

3. **SyftBox APIs**: SyftBox APIs are applications designed to interact with data that are either private to a single Datasite or synced from other Datasites. These APIs can perform various tasks, such as data analysis, machine learning, or visualization, while respecting the privacy constraints of the data they operate on.

## Why SyftBox Matters

SyftBox addresses one of the most significant challenges in the PETs landscape: deployment complexity. SyftBox simplifies this process through its distributed network architecture and modular design, making PETs deployment as intuitive as managing a synchronized file system.

By transforming complex PETs deployment into a familiar network-based paradigm, SyftBox enables developers to focus on building privacy-preserving applications rather than wrestling with infrastructure challenges. This approach particularly shines in Federated Learning scenarios, where the coordination of distributed training traditionally requires significant engineering effort but becomes a natural extension of SyftBox's network architecture.

In the following sections, we will explore the technical aspects of SyftBox, including its architecture, components, and how to get started with building PETs applications using this powerful framework.

## Install SyftBox

To install SyftBox, simply run the following command:

```sh
curl -LsSf https://syftbox.openmined.org/install.sh | sh
```

:::info curl
You'll need `curl` installed for this to work. There's a high probability you already have it installed by default on your OS. If for any reason you don't have it, check out these installation guides depending on your platform:

- [Linux](https://everything.curl.dev/install/linux.html)
- [MacOS](https://everything.curl.dev/install/macos.html)
- [Windows](https://everything.curl.dev/install/windows/index.html)
  :::

You'll see an output similar to this:

```
 ____         __ _   ____
/ ___| _   _ / _| |_| __ )  _____  __
\___ \| | | | |_| __|  _ \ / _ \ \/ /
 ___) | |_| |  _| |_| |_) | (_) >  <
|____/ \__, |_|  \__|____/ \___/_/\_\
       |___/

Installing uv
Installing SyftBox (with managed Python 3.12)
Installation completed!

Start the client now? [y/n]
```

Press `y` and `Enter` to start the client. If it's the first time you run SyftBox, you will also be prompted to choose the location for your **sync directory** (representing your Datasite) and to enter your email address:

```
Starting SyftBox client...
Where do you want SyftBox to store data? Press Enter for default (/home/...):

Enter your email address:
```

That's it! You now have SyftBox running on your local machine!

:::info
Make sure to keep your terminal open to keep the client running. To restart the client, simply run the install command again.
:::

### SyftBox Stats Dashboard

After connecting your client to the Syft network, check out the [**_Stats Dashboard_**](https://syftbox.openmined.org/datasites/aggregator@openmined.org/syft_stats.html), where you can see a list of _all_ connected Datasites and their public files! Can you see yours?


## Files and Folders

SyftBox interacts with specific files and directories on your computer:

- The configuration file (located at `~/.syftbox/config.json`)
- The _sync directory_ (selected during installation, typically located at `~/SyftBox` or `~/Desktop/SyftBox`)
  (`~` refers to your User Home Directory).

The configuration file is primarily used by the SyftBox client and contains information essential for syncing your Datasite with the Syft network.

The sync directory, which represents your Datasite, has a more organized structure:

```
SyftBox
├── apis
│   └── ...
├── datasites
│   └── ...
├── logs
│   └── ...
└── plugins
    └── ...
```

The sync directory consists of four main subdirectories:

- `apis`: This directory houses all your SyftBox APIs , which are the core components for interacting with and processing data within the SyftBox ecosystem.
- `datasites`: This directory contains synced data from other clients connected to the Syft network. Each datasite is uniquely identified by the email address of the corresponding network user, ensuring proper organization and access control.
- `logs`: SyftBox stores all log files in this directory, which can be invaluable for troubleshooting and monitoring the system's behavior.
- `plugins`: This directory is designed to host any additional plugins or extensions that enhance the functionality of SyftBox, allowing for customization and extensibility of the platform.

## APIs

In essence, a SyftBox API is a script designed to interact with your own data and/or data synced from other datasites on your machine. These APIs form the backbone of the SyftBox ecosystem, enabling users to process, analyze, and manipulate data in a privacy-preserving manner.

### Installing a SyftBox API

Installing a SyftBox API is a straightforward process. Simply drag the API folder into your `apis` directory, and you're done! The SyftBox client automatically checks for new APIs every 10 seconds and executes them without any further intervention. This seamless installation process ensures that users can quickly and easily expand the functionality of their SyftBox setup.

### Creating a SyftBox API

Creating a new SyftBox API is equally simple. The main requirement is to organize your API into a folder containing a `run.sh` script. This script holds the instructions for running the SyftBox API. While SyftBox provides a Python SDK to aid developers in creating APIs using Python, the platform does not impose any limitations on the programming language used. As long as the necessary commands can be invoked from the main `run.sh` file, the API can be written in any language of your choice.

A typical template for a Python-based SyftBox API includes two key files:

1. `run.sh`: This script contains the instructions to set up the environment and execute the main Python script.
2. `main.py`: This file holds the actual Python code for the API, utilizing the SyftBox Python SDK to interact with the platform and data.

To familiarize yourself with the process of creating SyftBox APIs, we recommend exploring the tutorials provided in this documentation. These tutorials offer step-by-step guidance and practical examples to help you get started with building your own APIs and leveraging the full potential of the SyftBox platform.
"""
