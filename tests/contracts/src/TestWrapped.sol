// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

// Deliberately minimal test fixture, not a production token or DeFi protocol.
contract TestWrapped {
    mapping(address => uint256) public balanceOf;
    uint8 public constant decimals = 18;

    function deposit() external payable {
        balanceOf[msg.sender] += msg.value;
    }
}
