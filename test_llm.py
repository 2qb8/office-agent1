import os
import unittest

from dotenv import load_dotenv

from agent.llm_factory import create_llm


class LLMTests(unittest.TestCase):

    def test_configuration_exists(self):
        load_dotenv("config/.env")

        self.assertTrue(
            os.getenv("LLM_BASE_URL")
        )

        self.assertTrue(
            os.getenv("LLM_MODEL")
        )


if __name__ == "__main__":
    unittest.main()