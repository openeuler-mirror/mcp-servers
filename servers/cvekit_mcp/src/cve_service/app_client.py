import logging
from typing import Any
from uuid import uuid4
import httpx
import argparse
import json
import logging
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    AgentCard,
    MessageSendParams,
    SendStreamingMessageRequest,
)
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    EXTENDED_AGENT_CARD_PATH,
)

def parse_args():
    parser = argparse.ArgumentParser(description="A2A Client - 支持命令行指定CVE-ID")
    parser.add_argument(
        "--cve-id",
        required=True,
        type=str,
        help="目标CVE编号（例如：CVE-2025-38051）"
    )

    parser.add_argument(
        "--action",
        default="branches-analysis",
        choices=["branches-analysis", "patch-apply-pr-creation", "pipeline", "package-pipeline"],
        help="操作类型（默认：branches-analysis）"
    )
    parser.add_argument(
        "--branches",
        type=str,
        help="待应用补丁和提交pr的分支列表"
    )
    parser.add_argument(
        "--signer-name",
        type=str,
        help="签名人姓名"
    )
    parser.add_argument(
        "--signer-email",
        type=str,
        help="签名人邮箱"
    )
    parser.add_argument(
        "--clone-dir",
        type=str,
        default=""
    )
    parser.add_argument(
        "--package-name",
        type=str,
        help="软件包名称"
    )
    parser.add_argument(
        "--branch",
        type=str,
        help="软件包分支"
    )
    return parser.parse_args()

async def main() -> None:
    # Configure logging to show
    #  INFO level messages
    args = parse_args()
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)  # Get a logger instance
    # --8<-- [start:A2ACardResolver]

    base_url = 'http://localhost:9991'

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as httpx_client:
        # Initialize A2ACardResolver
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=base_url,
            # agent_card_path uses default, extended_agent_card_path also uses default
        )
        # --8<-- [end:A2ACardResolver]

        # Fetch Public Agent Card and Initialize Client
        final_agent_card_to_use: AgentCard | None = None

        try:
            logger.info(
                f'Attempting to fetch public agent card from: {base_url}{AGENT_CARD_WELL_KNOWN_PATH}'
            )
            _public_card = (
                await resolver.get_agent_card()
            )  # Fetches from default public path
            logger.info('Successfully fetched public agent card:')
            logger.info(
                _public_card.model_dump_json(indent=2, exclude_none=True)
            )
            final_agent_card_to_use = _public_card
            logger.info(
                '\nUsing PUBLIC agent card for client initialization (default).'
            )

            if _public_card.supports_authenticated_extended_card:
                try:
                    logger.info(
                        f'\nPublic card supports authenticated extended card. Attempting to fetch from: {base_url}{EXTENDED_AGENT_CARD_PATH}'
                    )
                    auth_headers_dict = {
                        'Authorization': 'Bearer dummy-token-for-extended-card'
                    }
                    _extended_card = await resolver.get_agent_card(
                        relative_card_path=EXTENDED_AGENT_CARD_PATH,
                        http_kwargs={'headers': auth_headers_dict},
                    )
                    logger.info(
                        'Successfully fetched authenticated extended agent card:'
                    )
                    logger.info(
                        _extended_card.model_dump_json(
                            indent=2, exclude_none=True
                        )
                    )
                    final_agent_card_to_use = (
                        _extended_card  # Update to use the extended card
                    )
                    logger.info(
                        '\nUsing AUTHENTICATED EXTENDED agent card for client initialization.'
                    )
                except Exception as e_extended:
                    logger.warning(
                        f'Failed to fetch extended agent card: {e_extended}. Will proceed with public card.',
                        exc_info=True,
                    )
            elif (
                _public_card
            ):  # supports_authenticated_extended_card is False or None
                logger.info(
                    '\nPublic card does not indicate support for an extended card. Using public card.'
                )

        except Exception as e:
            logger.error(
                f'Critical error fetching public agent card: {e}', exc_info=True
            )
            raise RuntimeError(
                'Failed to fetch the public agent card. Cannot continue.'
            ) from e

        # --8<-- [start:send_message]
        client = A2AClient(
            httpx_client=httpx_client, agent_card=final_agent_card_to_use
        )

        logger.info('A2AClient initialized.')
        message_text_dict = {
            "action": args.action,
            "cve_id": args.cve_id
        }

        if args.action == "patch-apply-pr-creation":
            message_text_dict["branches"] = args.branches
            message_text_dict["signer_name"] = args.signer_name
            message_text_dict["signer_email"] = args.signer_email
        if args.action == "pipeline":
            message_text_dict["branches"] = args.branches
            message_text_dict["signer_name"] = args.signer_name
            message_text_dict["signer_email"] = args.signer_email
            if args.clone_dir:
                message_text_dict["clone_dir"] = args.clone_dir
        if args.action == "package-pipeline":
            message_text_dict["package_name"] = args.package_name
            message_text_dict["branch"] = args.branch

        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [
                    {'kind': 'text', 'text': str(message_text_dict).replace("'", '"')}  
                ],
                'messageId': uuid4().hex,
            },
        }

        streaming_request = SendStreamingMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(**send_message_payload)
        )
        async for chunk in client.send_message_streaming(streaming_request):
            chunk_dict = chunk.model_dump(mode='json', exclude_none=True)
            logging.info(json.dumps(chunk_dict["result"], ensure_ascii=False))


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
