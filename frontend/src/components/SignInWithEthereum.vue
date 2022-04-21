<script setup lang="ts">
    import { ethers } from 'ethers';
    import { SiweMessage } from 'siwe';

    const domain = window.location.host;
    const origin = window.location.origin;
    const provider = new ethers.providers.Web3Provider(window.ethereum);
    const signer = provider.getSigner();

    const BACKEND_ADDR = "http://localhost:8001";
    async function createSiweMessage(address, statement) {
        const res = await fetch(`${BACKEND_ADDR}/siwe/nonce`, {
            credentials: 'include',
        });
        const message = new SiweMessage({
            domain,
            address,
            statement,
            uri: origin,
            version: '1',
            chainId: '1',
            nonce: await res.text()
        });
        return message.prepareMessage();
    }

    function connectWallet() {
        provider.send('eth_requestAccounts', [])
            .catch(() => console.log('user rejected request'));
    }

    async function signInWithEthereum() {
        const message = await createSiweMessage(
            await signer.getAddress(),
            'Sign in with Ethereum to the app.'
        );
        const signature = await signer.signMessage(message);

        const res = await fetch(`${BACKEND_ADDR}/siwe/verify`, {
            method: "POST",
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message, signature }),
            credentials: 'include'
        });
        console.log(await res.text());
    }

    async function getInformation() {
        const res = await fetch(`${BACKEND_ADDR}/siwe/personal_information`, {
            credentials: 'include',
        });
        console.log(await res.text());
    }
</script>

<template>
    <q-btn color="secondary" @click="connectWallet">
        Connect Wallet
    </q-btn>

    <q-btn color="secondary" @click="signInWithEthereum">
        Sign In With Ethereum
    </q-btn>

    <q-btn color="secondary" @click="getInformation">
        Get Information
    </q-btn>
</template>
